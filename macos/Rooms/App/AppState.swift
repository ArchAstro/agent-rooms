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
    var roomLoadError: String?
    var isLoadingRooms = false
    var hasLoadedRooms = false
    var isSendingMessage = false

    // MARK: Network tray state

    var selectedTab: TrayTab = .chat {
        didSet {
            if oldValue == .activity && selectedTab != .activity {
                newEventIDs.subtract(visibleCurrentEventIDs)
            }
        }
    }
    var availableNetworks = TrayPlaceholders.networks
    var selectedNetwork = TrayPlaceholders.networks[0]
    var members = TrayPlaceholders.members
    var threads = TrayPlaceholders.threads
    var selectedThread = TrayPlaceholders.threads[0]
    var messages = TrayPlaceholders.messages
    var tasks = TrayPlaceholders.tasks
    var workstream = TrayPlaceholders.workstream
    var events = TrayPlaceholders.events
    var activityFilter: StreamEvent.Level = .all {
        willSet {
            if selectedTab == .activity && !suppressActivityReadTracking {
                newEventIDs.subtract(visibleCurrentEventIDs)
            }
        }
    }
    var activityPaused = false
    var typingByThread = ["thread_general": "Fleet"]
    var newEventIDs: Set<String> = []

    var currentMembers: [NetworkMember] {
        members.filter { $0.networkID == selectedNetwork.id }
    }
    var currentThreads: [NetworkThread] {
        threads.filter { $0.networkID == selectedNetwork.id }
    }
    var currentMessages: [ChatMessage] {
        messages.filter { $0.threadID == selectedThread.id }
    }
    var currentTasks: [ThreadTask] {
        tasks.filter { $0.threadID == selectedThread.id }
    }
    var currentWorkstream: [WorkstreamItem] {
        workstream.filter { $0.networkID == selectedNetwork.id }
    }
    var currentEvents: [StreamEvent] {
        events.filter { $0.networkID == selectedNetwork.id }
    }
    var visibleCurrentEventIDs: [String] {
        currentEvents.filter { $0.matches(activityFilter) }.map(\.id)
    }
    var totalUnreadCount: Int {
        threads.reduce(0) { $0 + $1.unreadCount }
    }

    var toast: String?
    private var toastTask: Task<Void, Never>?
    private var liveFeedTask: Task<Void, Never>?
    private var pendingLiveEvents = TrayPlaceholders.liveFeed
    private var suppressActivityReadTracking = false

    func showToast(_ message: String) {
        toastTask?.cancel()
        toast = message
        toastTask = Task {
            try? await Task.sleep(nanoseconds: 1_900_000_000)
            guard !Task.isCancelled else { return }
            toast = nil
        }
    }

    func selectNetwork(_ network: NetworkSnapshot, markVisibleContentRead: Bool = true) {
        if markVisibleContentRead && selectedTab == .activity {
            newEventIDs.subtract(visibleCurrentEventIDs)
        }
        let networkChanged = selectedNetwork.id != network.id
        selectedNetwork = network
        if networkChanged,
           let defaultThread = currentThreads.first(where: \.isDefault) ?? currentThreads.first {
            selectedThread = defaultThread
        } else if networkChanged {
            selectedThread = NetworkThread(
                id: "",
                networkID: network.id,
                title: "No threads",
                isDefault: false,
                unreadCount: 0
            )
        }
        if markVisibleContentRead && selectedTab == .chat { markSelectedThreadRead() }
        showToast("Switched to \(network.name)")
    }

    func selectThread(_ thread: NetworkThread) {
        selectedThread = thread
        markSelectedThreadRead()
        showToast("Opened \(thread.title)")
    }

    func unreadCount(for networkID: String) -> Int {
        threads.filter { $0.networkID == networkID }.reduce(0) { $0 + $1.unreadCount }
    }

    func markSelectedThreadRead() {
        guard let index = threads.firstIndex(where: { $0.id == selectedThread.id }) else { return }
        threads[index].unreadCount = 0
    }

    func prepareActivityOverlay(_ event: StreamEvent) {
        if let network = availableNetworks.first(where: { $0.id == event.networkID }) {
            selectNetwork(network, markVisibleContentRead: false)
        }
        suppressActivityReadTracking = true
        activityFilter = .all
        suppressActivityReadTracking = false
        selectedTab = .activity
    }

    func openInFullApp(_ what: String, extraQueryItems: [URLQueryItem] = []) {
        guard let url = webAppURL(extraQueryItems: extraQueryItems),
              NSWorkspace.shared.open(url)
        else {
            showToast("Could not open the web app")
            return
        }
        showToast("\(what) opened in the web app")
    }

    func webAppURL(extraQueryItems: [URLQueryItem] = []) -> URL? {
        guard var components = URLComponents(string: archagentsURL) else { return nil }
        let basePath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = (basePath.isEmpty ? "" : "/\(basePath)") + "/teams/\(selectedNetwork.id)"
        components.queryItems = [
            URLQueryItem(name: "tab", value: selectedTab.rawValue.lowercased()),
            URLQueryItem(name: "thread", value: selectedThread.id),
        ] + extraQueryItems
        return components.url
    }

    @discardableResult
    func sendMessage(_ body: String, attachmentName: String? = nil) async -> Bool {
        guard !selectedThread.id.isEmpty else {
            showToast("No Team Room is selected")
            return false
        }
        guard let client else { return false }
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || attachmentName != nil else { return false }

        // Uploads are not yet exposed by the Swift SDK. Never pretend a local
        // filename crossed the network.
        guard attachmentName == nil else {
            showToast("Open the web app to attach files")
            return false
        }

        isSendingMessage = true
        defer { isSendingMessage = false }
        do {
            try await TeamRoomAPI.post(
                client: client,
                appID: activeAppID,
                userID: currentUserID,
                threadID: selectedThread.id,
                content: trimmed
            )
            await refreshRooms()
            showToast("Posted to Team Room")
            return true
        } catch let error as ApiError {
            showToast(error.message)
            return false
        } catch {
            showToast(error.localizedDescription)
            return false
        }
    }

    func deleteMessage(_ message: ChatMessage) async {
        guard message.isCurrentUser, let client else { return }
        do {
            try await client.threadMessages.delete(message: message.id)
            await refreshRooms()
            showToast("Message deleted")
        } catch let error as ApiError {
            showToast(error.message)
        } catch {
            showToast(error.localizedDescription)
        }
    }

    // MARK: Background refresh

    func startLiveFeed() {
        guard liveFeedTask == nil else { return }
        liveFeedTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(20))
                guard !Task.isCancelled, isSignedIn, !activityPaused else { continue }
                await refreshRooms()
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
            networkID: event.networkID,
            level: event.level,
            author: event.author,
            body: event.body,
            time: "now",
            sessionID: event.sessionID
        )
        pendingLiveEvents.append(event)
        withAnimation(.easeOut(duration: 0.3)) {
            events.insert(event, at: 0)
            if selectedTab != .activity
                || event.networkID != selectedNetwork.id
                || !event.matches(activityFilter)
            {
                newEventIDs.insert(event.id)
            }
        }
        onNewEvent?(event)
    }

    private let sessionStore = SessionStore()
    private var activeAuthServer: LoopbackCallbackServer?
    private var activeAppID: String?
    private var currentUserID: String?

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
        activeAppID = session.appId
        currentUserID = session.userId
        let client = makeClient(for: session)
        phase = .signedIn(client)
        await refreshRooms()
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
                orgName: result.orgName.isEmpty ? nil : result.orgName,
                appId: result.appId,
                userId: result.userId
            )
            sessionStore.save(session)
            userEmail = session.email
            orgName = session.orgName
            activeAppID = result.appId
            currentUserID = result.userId
            phase = .signedIn(makeClient(for: session))
            await refreshRooms()
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
                        email: email,
                        appId: nil,
                        userId: nil
                    )
                )
            }
            userEmail = email
            phase = .signedIn(client)
            await refreshRooms()
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
        activeAppID = nil
        currentUserID = nil
        hasLoadedRooms = false
        roomLoadError = nil
    }

    // MARK: Team Rooms

    /// Discover and hydrate every joined team containing a Team Room thread.
    /// Team pagination is fully drained inside TeamRoomAPI.
    func refreshRooms() async {
        guard let client else { return }
        isLoadingRooms = true
        roomLoadError = nil
        defer {
            isLoadingRooms = false
            hasLoadedRooms = true
        }

        do {
            let knownEventIDs = Set(events.map(\.id))
            let shouldNotify = hasLoadedRooms
            let me = try await client.users.me()
            currentUserID = me.id
            activeAppID = activeAppID ?? me.app
            if orgName == nil || orgName?.isEmpty == true {
                orgName = me.orgName
            }

            let loaded = try await TeamRoomAPI.load(
                client: client,
                currentUserID: currentUserID,
                organizationName: orgName
            )
            let currentUserEventIDs = Set(
                loaded.flatMap(\.messages)
                    .filter(\.isCurrentUser)
                    .map { "event-\($0.id)" }
            )
            availableNetworks = loaded.map(\.room)
            members = loaded.flatMap(\.members)
            threads = loaded.flatMap(\.threads)
            messages = loaded.flatMap(\.messages)
            events = loaded.flatMap(\.events)
            workstream = loaded.flatMap(\.workstream)
            tasks = []
            typingByThread = [:]
            newEventIDs.formIntersection(Set(events.map(\.id)))
            if shouldNotify {
                for event in events.reversed()
                where !knownEventIDs.contains(event.id)
                    && !currentUserEventIDs.contains(event.id)
                {
                    if selectedTab != .activity
                        || event.networkID != selectedNetwork.id
                        || !event.matches(activityFilter)
                    {
                        newEventIDs.insert(event.id)
                    }
                    onNewEvent?(event)
                }
            }

            if let prior = availableNetworks.first(where: { $0.id == selectedNetwork.id }) {
                selectedNetwork = prior
            } else if let first = availableNetworks.first {
                selectedNetwork = first
            } else {
                selectedNetwork = .empty
                selectedThread = .empty(networkID: "")
                return
            }
            selectedThread = currentThreads.first(where: { $0.id == selectedThread.id })
                ?? currentThreads.first(where: \.isDefault)
                ?? currentThreads.first
                ?? .empty(networkID: selectedNetwork.id)
        } catch let error as ApiError {
            if hasLoadedRooms && !availableNetworks.isEmpty {
                showToast("Room refresh failed: \(error.message)")
            } else {
                roomLoadError = error.message
            }
        } catch {
            if hasLoadedRooms && !availableNetworks.isEmpty {
                showToast("Room refresh failed")
            } else {
                roomLoadError = error.localizedDescription
            }
        }
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
