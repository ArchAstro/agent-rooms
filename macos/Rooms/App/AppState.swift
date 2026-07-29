import AppKit
import Foundation
import Observation
import SwiftUI
import ArchAstroPlatform

/// Top-level observable state for the app: session lifecycle and the
/// signed-in platform client. Views read this through the environment.
@MainActor
@Observable
final class AppState {
    /// UI shell hooks kept as closures so the product state remains testable
    /// without owning AppKit windows.
    var onNewEvent: ((StreamEvent) -> Void)?

    enum SessionPhase {
        case restoring
        case signedOut
        case signingIn
        case signedIn(PlatformClient)
    }

    var phase: SessionPhase = .restoring
    var signInError: String?
    /// True while a browser sign-in is waiting on the loopback redirect.
    var browserSignInPending = false
    /// Signed-in user's email, when known.
    var userEmail: String?
    /// Signed-in org name, when known.
    var orgName: String?

    // MARK: Tray state (placeholder-backed until wired to threads)

    var selectedTab: TrayTab = .picture {
        didSet {
            if oldValue == .stream && selectedTab != .stream {
                newEventIDs.removeAll()
            }
        }
    }
    var availableRooms: [RoomSnapshot] = TrayPlaceholders.rooms
    var selectedRoom: RoomSnapshot = TrayPlaceholders.rooms[0]
    var requests: [InboxRequest] = TrayPlaceholders.requests
    var events: [StreamEvent] = TrayPlaceholders.events
    var streamFilter: StreamEvent.Filter = .all
    /// Latest ask answer, rendered as a Picture card.
    var askAnswer: (question: String, answer: String)?
    /// The Who's-working-on-what live view pinned to the Picture.
    var liveViewPinned = false
    /// Events that arrived since the stream was last in view.
    var newEventIDs: Set<String> = []

    /// Transient feedback toast (mirrors the mock's toast layer).
    var toast: String?
    private var toastTask: Task<Void, Never>?
    private var liveFeedTask: Task<Void, Never>?
    private var pendingLiveEvents = TrayPlaceholders.liveFeed

    var inboxCount: Int { requests.count }

    func showToast(_ message: String) {
        toastTask?.cancel()
        toast = message
        toastTask = Task {
            try? await Task.sleep(nanoseconds: 1_900_000_000)
            guard !Task.isCancelled else { return }
            toast = nil
        }
    }

    func selectRoom(_ room: RoomSnapshot) {
        selectedRoom = room
        askAnswer = nil
        showToast("Switched to \(room.name)")
    }

    func resolveRequest(_ request: InboxRequest, feedback: String) {
        requests.removeAll { $0.id == request.id }
        showToast(feedback)
    }

    func deferRequest(_ request: InboxRequest) {
        showToast("\(request.kind.label) stays in your inbox")
    }

    /// Anything the tray can't do yet opens in the full app.
    func openInFullApp(_ what: String) {
        showToast("\(what) opened in the full app")
    }

    func toggleLiveViewPinned() {
        liveViewPinned.toggle()
        showToast(liveViewPinned ? "Live view pinned to The Picture" : "Live view unpinned")
    }

    /// Staggered clear, mirroring the mock's cascade.
    func clearInbox() {
        let pending = requests
        Task {
            for request in pending {
                withAnimation(.easeOut(duration: 0.25)) {
                    requests.removeAll { $0.id == request.id }
                }
                try? await Task.sleep(nanoseconds: 55_000_000)
            }
            showToast("Inbox cleared")
        }
    }

    /// Placeholder ask — the live app routes this through the room's
    /// resident agent and grounds the answer in the stream.
    func ask(_ question: String) {
        let lower = question.lowercased()
        let answer: String
        if lower.contains("who") || lower.contains("working") || lower.contains("doing") {
            answer = "Calvin is watching Code Search deploy, Rob has the cleanup ledger local, Bruno just landed N-org networks, and Vivek is watching the corrected magic-link stack in CI."
        } else if lower.contains("need") || lower.contains("attention") || lower.contains("inbox") {
            answer = "Three requests need you: one deployment decision, one handoff, and one review note. Nothing is customer-critical."
        } else if lower.contains("summary") || lower.contains("today") || lower.contains("happen") {
            answer = "Seven meaningful changes landed today. Code Search and Zoom OAuth are moving; the webhook identity patch is the only item with a substantive correctness warning."
        } else {
            answer = "The room found 42 relevant posts across 18 active sessions. In the live app, the resident synthesizes a sourced answer here and preserves the question as a reusable view."
        }
        askAnswer = (question, answer)
        showToast("Answer grounded in 42 room posts")
    }

    // MARK: Live feed simulation

    /// Simulate the always-running stream: a new event lands every so
    /// often, marked NEW until the stream is next in view. Replaced by
    /// the real ApiChatChannel subscription in the next milestone.
    func startLiveFeed() {
        guard liveFeedTask == nil else { return }
        liveFeedTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64.random(in: 14_000_000_000...24_000_000_000))
                guard !Task.isCancelled, isSignedIn else { continue }
                deliverNextLiveEvent()
            }
        }
    }

    func stopLiveFeed() {
        liveFeedTask?.cancel()
        liveFeedTask = nil
    }

    /// Internal for tests — the timer loop calls this on cadence.
    func deliverNextLiveEvent() {
        guard !pendingLiveEvents.isEmpty else { return }
        var event = pendingLiveEvents.removeFirst()
        event = StreamEvent(
            id: "\(event.id)-\(UUID().uuidString.prefix(4))",
            kind: event.kind,
            author: event.author,
            body: event.body,
            time: "now",
            isYou: event.isYou
        )
        pendingLiveEvents.append(event)
        withAnimation(.easeOut(duration: 0.3)) {
            events.insert(event, at: 0)
            if selectedTab != .stream {
                newEventIDs.insert(event.id)
            }
        }
        onNewEvent?(event)
    }

    private let sessionStore = SessionStore()
    private var activeAuthServer: LoopbackCallbackServer?

    var isSignedIn: Bool {
        if case .signedIn = phase { return true }
        return false
    }

    var client: PlatformClient? {
        if case .signedIn(let client) = phase { return client }
        return nil
    }

    // MARK: Configuration (Settings window)

    var baseURL: String {
        get { UserDefaults.standard.string(forKey: "baseURL") ?? "https://platform.archastro.ai" }
        set { UserDefaults.standard.set(newValue, forKey: "baseURL") }
    }

    /// ArchAgents web app that hosts the browser sign-in handoff.
    var archagentsURL: String {
        get { UserDefaults.standard.string(forKey: "archagentsURL") ?? ArchAgentsAuth.defaultArchAgentsURL }
        set { UserDefaults.standard.set(newValue, forKey: "archagentsURL") }
    }

    /// App slug the sign-in handoff authenticates against.
    var appSlug: String {
        get { UserDefaults.standard.string(forKey: "appSlug") ?? ArchAgentsAuth.defaultAppSlug }
        set { UserDefaults.standard.set(newValue, forKey: "appSlug") }
    }

    /// Publishable key — only needed for the email/password fallback.
    var publishableKey: String {
        get { UserDefaults.standard.string(forKey: "publishableKey") ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: "publishableKey") }
    }

    var overlayEnabled: Bool = {
        let defaults = UserDefaults.standard
        // Event bodies may contain private room context, so previews are opt-in.
        guard defaults.object(forKey: "overlayEnabled") != nil else { return false }
        return defaults.bool(forKey: "overlayEnabled")
    }() {
        didSet {
            UserDefaults.standard.set(overlayEnabled, forKey: "overlayEnabled")
        }
    }

    var overlayAutoDismiss: Bool = {
        let defaults = UserDefaults.standard
        guard defaults.object(forKey: "overlayAutoDismiss") != nil else { return true }
        return defaults.bool(forKey: "overlayAutoDismiss")
    }() {
        didSet {
            UserDefaults.standard.set(
                overlayAutoDismiss,
                forKey: "overlayAutoDismiss"
            )
        }
    }

    var overlayDuration: Double = {
        let value = UserDefaults.standard.double(forKey: "overlayDuration")
        return value > 0 ? value : 6
    }() {
        didSet {
            UserDefaults.standard.set(overlayDuration, forKey: "overlayDuration")
        }
    }

    // MARK: Session lifecycle

    /// Restore a persisted session from the Keychain, if any.
    func restoreSession() async {
        guard case .restoring = phase else { return }
        guard let session = sessionStore.load() else {
            phase = .signedOut
            return
        }
        userEmail = session.email
        orgName = session.orgName
        phase = .signedIn(makeClient(for: session))
    }

    /// Browser sign-in through ArchAgents — opens archagents.com's
    /// `/org/cli-auth` handoff (the same flow the archagent CLI uses) and
    /// receives the session tokens on a loopback redirect. If the browser
    /// already has an ArchAgents session, this completes without any
    /// re-authentication.
    func signInWithBrowser() async {
        phase = .signingIn
        browserSignInPending = true
        signInError = nil
        defer {
            browserSignInPending = false
            activeAuthServer = nil
        }

        do {
            let server = try await LoopbackCallbackServer.start()
            activeAuthServer = server
            let loginURL = try ArchAgentsAuth.loginURL(
                archagentsURL: archagentsURL,
                appSlug: appSlug,
                redirectURI: server.callbackURL
            )
            NSWorkspace.shared.open(loginURL)

            let callback = try await server.waitForCallback()
            let result = try ArchAgentsAuth.parseCallback(callback)

            let session = StoredSession(
                kind: .archagents,
                baseURL: baseURL,
                accessToken: result.accessToken,
                refreshToken: result.refreshToken,
                email: result.email.isEmpty ? nil : result.email,
                orgName: result.orgName.isEmpty ? nil : result.orgName
            )
            sessionStore.save(session)
            userEmail = session.email
            orgName = session.orgName
            phase = .signedIn(makeClient(for: session))
        } catch ArchAgentsAuth.AuthError.cancelled {
            phase = .signedOut
        } catch LoopbackCallbackServer.ServerError.cancelled {
            phase = .signedOut
        } catch let error as ApiError {
            signInError = error.message
            phase = .signedOut
        } catch {
            signInError = error.localizedDescription
            phase = .signedOut
        }
    }

    /// Abort a pending browser sign-in.
    func cancelSignIn() {
        activeAuthServer?.cancel()
    }

    /// Email/password fallback via `PlatformClient.withCredentials`.
    func signIn(email: String, password: String) async {
        guard !publishableKey.isEmpty else {
            signInError = "Set a publishable key in Settings first."
            return
        }
        phase = .signingIn
        signInError = nil
        do {
            let client = try await PlatformClient.withCredentials(
                apiKey: publishableKey,
                email: email,
                password: password,
                baseUrl: baseURL
            )
            if let accessToken = client.http.currentAccessToken() {
                sessionStore.save(
                    StoredSession(
                        kind: .password,
                        baseURL: baseURL,
                        accessToken: accessToken,
                        refreshToken: client.refreshToken,
                        apiKey: publishableKey,
                        email: email
                    )
                )
            }
            userEmail = email
            phase = .signedIn(client)
        } catch let error as ApiError {
            signInError = error.message
            phase = .signedOut
        } catch {
            signInError = "Could not sign in: \(error.localizedDescription)"
            phase = .signedOut
        }
    }

    func signOut() async {
        if let client {
            await client.close()
        }
        sessionStore.clear()
        phase = .signedOut
        userEmail = nil
        orgName = nil
    }

    // MARK: Client construction

    /// Build a client for a stored session with automatic 401 refresh
    /// that persists rotated tokens back to the Keychain.
    ///
    /// Browser (archagents) sessions carry no app key, so they refresh via
    /// `/api/v1/auth/refresh/keyless` — the endpoint added for CLI
    /// org-login sessions. Password sessions refresh via the standard
    /// publishable-key `/api/v1/auth/refresh`.
    private func makeClient(for session: StoredSession) -> PlatformClient {
        var headers: [String: String] = [:]
        if let apiKey = session.apiKey {
            headers["x-archastro-api-key"] = apiKey
        }
        let client = PlatformClient(
            baseUrl: session.baseURL,
            accessToken: session.accessToken,
            defaultHeaders: headers
        )
        if let refreshToken = session.refreshToken {
            client.setRefreshToken(refreshToken)
        }

        // Refresh runs on a separate refresh-only HTTP client so it can
        // never re-enter the main client's 401 retry.
        let refreshHttp = HttpClient(
            baseUrl: session.baseURL,
            defaultHeaders: headers,
            refreshOnly: true
        )
        let refreshAuth = AuthClient(http: refreshHttp)
        let store = sessionStore
        let kind = session.kind
        client.http.setRefreshHandler { [weak client] in
            guard let client, let currentRefresh = client.refreshToken else {
                throw PlatformClientError.refreshFailed("No refresh token available")
            }

            let newAccessToken: String
            let newRefreshToken: String?
            switch kind {
            case .archagents:
                // Keyless rotation: the refresh token is the credential.
                let data: JSONValue = try await refreshHttp.request(
                    "/api/v1/auth/refresh/keyless",
                    method: "POST",
                    body: ["refresh_token": JSONValue.string(currentRefresh)]
                )
                guard let token = data["access_token"]?.stringValue else {
                    throw PlatformClientError.refreshFailed("Refresh did not return an access token")
                }
                newAccessToken = token
                newRefreshToken = data["refresh_token"]?.stringValue
            case .password:
                let refreshed = try await refreshAuth.refresh(refreshToken: currentRefresh)
                guard let token = refreshed.accessToken else {
                    throw PlatformClientError.refreshFailed("Refresh did not return an access token")
                }
                newAccessToken = token
                newRefreshToken = refreshed.refreshToken
            }

            client.setAccessToken(newAccessToken)
            if let newRefreshToken {
                client.setRefreshToken(newRefreshToken)
            }
            // The rotated refresh token is single-use — persist immediately
            // so a relaunch never replays a consumed token.
            var updated = session
            updated.accessToken = newAccessToken
            updated.refreshToken = newRefreshToken ?? currentRefresh
            store.save(updated)
            return newAccessToken
        }
        return client
    }
}
