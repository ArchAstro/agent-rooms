import Foundation
import Testing
@testable import Rooms

@Suite struct AppStateTests {
    @Test @MainActor func starts_restoring_with_placeholder_rooms() {
        let state = AppState()
        if case .restoring = state.phase {
            // expected
        } else {
            Issue.record("Expected initial phase to be .restoring")
        }
        #expect(!state.rooms.isEmpty)
        #expect(state.client == nil)
        #expect(!state.isSignedIn)
    }

    @Test @MainActor func base_url_defaults_to_production() {
        let state = AppState()
        #expect(state.baseURL.hasPrefix("https://"))
    }
}

@Suite struct StoredSessionTests {
    @Test func round_trips_through_json() throws {
        let session = StoredSession(
            kind: .archagents,
            baseURL: "https://platform.archastro.ai",
            accessToken: "token",
            refreshToken: "refresh",
            email: "dev@example.com",
            orgName: "Acme"
        )
        let data = try JSONEncoder().encode(session)
        let decoded = try JSONDecoder().decode(StoredSession.self, from: data)
        #expect(decoded.kind == .archagents)
        #expect(decoded.accessToken == "token")
        #expect(decoded.refreshToken == "refresh")
        #expect(decoded.orgName == "Acme")
        #expect(decoded.apiKey == nil)
    }
}
