import Foundation
import Testing
@testable import Rooms

@Suite struct AppStateTests {
    @Test @MainActor func starts_restoring_with_placeholder_content() {
        let state = AppState()
        if case .restoring = state.phase {
            // expected
        } else {
            Issue.record("Expected initial phase to be .restoring")
        }
        #expect(!state.availableRooms.isEmpty)
        #expect(state.inboxCount == state.requests.count)
        #expect(state.selectedTab == .picture)
        #expect(state.client == nil)
        #expect(!state.isSignedIn)
    }

    @Test @MainActor func resolving_requests_drains_the_inbox() {
        let state = AppState()
        let initial = state.inboxCount
        #expect(initial > 0)
        state.resolveRequest(state.requests[0])
        #expect(state.inboxCount == initial - 1)
        state.clearInbox()
        #expect(state.inboxCount == 0)
    }

    @Test @MainActor func ask_produces_a_grounded_answer_card() {
        let state = AppState()
        #expect(state.askAnswer == nil)
        state.ask("who is working on what?")
        #expect(state.askAnswer?.question == "who is working on what?")
        #expect(state.askAnswer?.answer.isEmpty == false)
        state.selectRoom(state.availableRooms[1])
        #expect(state.askAnswer == nil)
        #expect(state.selectedRoom.id == state.availableRooms[1].id)
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
