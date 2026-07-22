import Foundation

/// Browser sign-in through ArchAgents — the same OAuth-like handoff the
/// archagent CLI uses against archagents.com:
///
/// 1. Open `{archagents}/org/cli-auth?slug=agentnetwork&redirect_uri=
///    http://localhost:{port}/callback` in the browser.
/// 2. The user signs in on archagents.com (skipped entirely when the
///    browser already has a session — the route short-circuits).
/// 3. archagents.com redirects to the loopback callback with the session
///    as query parameters (`access_token`, `refresh_token`, `app`,
///    `org`, `user`, …) — names shared with the CLI via the
///    developer-platform-sdk's CLI_CALLBACK_PARAMS contract.
///
/// Any loopback port is accepted (`isValidRedirectUri` checks host only),
/// so the listener binds an ephemeral port like the CLI does.
enum ArchAgentsAuth {
    static let defaultArchAgentsURL = "https://archagents.com"
    static let defaultAppSlug = "agentnetwork"

    struct Result: Equatable, Sendable {
        var accessToken: String
        var refreshToken: String
        var expiresIn: Int?
        var appId: String
        var appName: String
        var orgId: String
        var orgName: String
        var userId: String
        var email: String
        var sandboxId: String?
    }

    enum AuthError: LocalizedError, Equatable {
        case cancelled
        case serverError(String)
        case missingParams
        case invalidURL(String)

        var errorDescription: String? {
            switch self {
            case .cancelled:
                "Sign-in was cancelled."
            case .serverError(let code):
                "Sign-in failed: \(friendlyError(code))"
            case .missingParams:
                "The sign-in response was missing required fields."
            case .invalidURL(let url):
                "Invalid ArchAgents URL: \(url)"
            }
        }
    }

    /// `{archagents}/org/cli-auth?slug={appSlug}&redirect_uri={redirectURI}`
    static func loginURL(
        archagentsURL: String,
        appSlug: String,
        redirectURI: String,
        email: String? = nil
    ) throws -> URL {
        guard var components = URLComponents(string: archagentsURL) else {
            throw AuthError.invalidURL(archagentsURL)
        }
        var path = components.path
        while path.hasSuffix("/") { path.removeLast() }
        components.path = path + "/org/cli-auth"
        var items = [
            URLQueryItem(name: "slug", value: appSlug),
            URLQueryItem(name: "redirect_uri", value: redirectURI),
        ]
        if let email, !email.isEmpty {
            items.append(URLQueryItem(name: "email", value: email))
        }
        components.queryItems = items
        guard let url = components.url else {
            throw AuthError.invalidURL(archagentsURL)
        }
        return url
    }

    /// Parse the loopback callback. Mirrors the CLI's parseOrgCallback
    /// against the CLI_CALLBACK_PARAMS names: `access_token`,
    /// `refresh_token`, `app`, `org`, `user` required; `app_name`,
    /// `org_name`, `email`, `expires_in`, `sandbox` optional; `error`
    /// rejects.
    static func parseCallback(_ url: URL) throws -> Result {
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let params = Dictionary(
            items.compactMap { item in item.value.map { (item.name, $0) } },
            uniquingKeysWith: { first, _ in first }
        )

        if let error = params["error"] {
            throw error == "cancelled" ? AuthError.cancelled : AuthError.serverError(error)
        }
        guard
            let accessToken = params["access_token"], !accessToken.isEmpty,
            let refreshToken = params["refresh_token"], !refreshToken.isEmpty,
            let appId = params["app"], !appId.isEmpty,
            let orgId = params["org"], !orgId.isEmpty,
            let userId = params["user"], !userId.isEmpty
        else {
            throw AuthError.missingParams
        }

        return Result(
            accessToken: accessToken,
            refreshToken: refreshToken,
            expiresIn: params["expires_in"].flatMap(Int.init),
            appId: appId,
            appName: params["app_name"] ?? appId,
            orgId: orgId,
            orgName: params["org_name"] ?? "",
            userId: userId,
            email: params["email"] ?? "",
            sandboxId: params["sandbox"]
        )
    }

    static func friendlyError(_ raw: String) -> String {
        switch raw {
        case "no_access": "This account does not have access to ArchAgents."
        case "auth_failed": "Authentication failed. Please try again."
        default: raw
        }
    }
}
