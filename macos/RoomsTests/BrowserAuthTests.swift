import Foundation
import Testing
@testable import Rooms

@Suite struct ArchAgentsAuthTests {
    @Test func login_url_matches_the_cli_handoff_shape() throws {
        let url = try ArchAgentsAuth.loginURL(
            archagentsURL: "https://archagents.com",
            appSlug: "agentnetwork",
            redirectURI: "http://localhost:54321/callback"
        )
        #expect(url.host() == "archagents.com")
        #expect(url.path() == "/org/cli-auth")
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        #expect(query.contains(URLQueryItem(name: "slug", value: "agentnetwork")))
        #expect(query.contains(URLQueryItem(name: "redirect_uri", value: "http://localhost:54321/callback")))
        #expect(!query.contains { $0.name == "email" })
    }

    @Test func login_url_carries_optional_email_hint() throws {
        let url = try ArchAgentsAuth.loginURL(
            archagentsURL: "http://localhost:3000/",
            appSlug: "agentnetwork",
            redirectURI: "http://localhost:54321/callback",
            email: "dev@example.com"
        )
        #expect(url.path() == "/org/cli-auth")
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        #expect(query.contains(URLQueryItem(name: "email", value: "dev@example.com")))
    }

    @Test func parses_the_cli_callback_params() throws {
        var components = URLComponents(string: "http://localhost:54321/callback")!
        components.queryItems = [
            URLQueryItem(name: "access_token", value: "at_1"),
            URLQueryItem(name: "refresh_token", value: "rt_1"),
            URLQueryItem(name: "expires_in", value: "3600"),
            URLQueryItem(name: "app", value: "dap_1"),
            URLQueryItem(name: "app_name", value: "ArchAgents"),
            URLQueryItem(name: "org", value: "org_1"),
            URLQueryItem(name: "org_name", value: "Acme"),
            URLQueryItem(name: "user", value: "usr_1"),
            URLQueryItem(name: "email", value: "dev@example.com"),
            URLQueryItem(name: "sandbox", value: "sbx_1"),
        ]
        let result = try ArchAgentsAuth.parseCallback(components.url!)
        #expect(result.accessToken == "at_1")
        #expect(result.refreshToken == "rt_1")
        #expect(result.expiresIn == 3600)
        #expect(result.appId == "dap_1")
        #expect(result.appName == "ArchAgents")
        #expect(result.orgId == "org_1")
        #expect(result.orgName == "Acme")
        #expect(result.userId == "usr_1")
        #expect(result.email == "dev@example.com")
        #expect(result.sandboxId == "sbx_1")
    }

    @Test func optional_params_default_sensibly() throws {
        let result = try ArchAgentsAuth.parseCallback(
            URL(string: "http://localhost:1/callback?access_token=a&refresh_token=r&app=dap_1&org=o&user=u")!
        )
        #expect(result.appName == "dap_1")
        #expect(result.orgName == "")
        #expect(result.email == "")
        #expect(result.expiresIn == nil)
        #expect(result.sandboxId == nil)
    }

    @Test func maps_error_params_to_errors() {
        #expect(throws: ArchAgentsAuth.AuthError.cancelled) {
            try ArchAgentsAuth.parseCallback(
                URL(string: "http://localhost:1/callback?error=cancelled")!
            )
        }
        #expect(throws: ArchAgentsAuth.AuthError.serverError("no_access")) {
            try ArchAgentsAuth.parseCallback(
                URL(string: "http://localhost:1/callback?error=no_access")!
            )
        }
    }

    @Test func missing_required_params_is_an_error() {
        #expect(throws: ArchAgentsAuth.AuthError.missingParams) {
            try ArchAgentsAuth.parseCallback(
                URL(string: "http://localhost:1/callback?access_token=a")!
            )
        }
    }
}

@Suite struct LoopbackCallbackServerTests {
    @Test func binds_an_ephemeral_port_and_delivers_the_redirect() async throws {
        let server = try await LoopbackCallbackServer.start()
        #expect(server.port > 0)

        async let callback = server.waitForCallback(timeout: 10)

        // Simulate the browser redirect with the CLI callback params.
        let url = URL(
            string: "\(server.callbackURL)?access_token=at&refresh_token=rt&app=dap&org=o&user=u"
        )!
        let (body, response) = try await URLSession.shared.data(from: url)
        let http = try #require(response as? HTTPURLResponse)
        #expect(http.statusCode == 200)
        #expect(String(decoding: body, as: UTF8.self).contains("Signed In"))

        let delivered = try await callback
        let result = try ArchAgentsAuth.parseCallback(delivered)
        #expect(result.accessToken == "at")
    }

    @Test func concurrent_servers_get_distinct_ports() async throws {
        let a = try await LoopbackCallbackServer.start()
        let b = try await LoopbackCallbackServer.start()
        #expect(a.port != b.port)
        a.cancel()
        b.cancel()
    }

    @Test func cancel_fails_a_pending_wait() async throws {
        let server = try await LoopbackCallbackServer.start()
        let waiter = Task { try await server.waitForCallback(timeout: 10) }
        try await Task.sleep(nanoseconds: 100_000_000)
        server.cancel()
        await #expect(throws: LoopbackCallbackServer.ServerError.self) {
            _ = try await waiter.value
        }
    }
}
