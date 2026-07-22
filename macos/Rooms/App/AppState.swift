import AppKit
import Foundation
import Observation
import ArchAstroPlatform

/// Top-level observable state for the app: session lifecycle and the
/// signed-in platform client. Views read this through the environment.
@MainActor
@Observable
final class AppState {
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

    /// Rooms shown in the sidebar. Placeholder until the rooms list is
    /// backed by the platform's thread APIs.
    var rooms: [Room] = Room.placeholders
    var selectedRoomID: Room.ID?

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
        selectedRoomID = nil
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
