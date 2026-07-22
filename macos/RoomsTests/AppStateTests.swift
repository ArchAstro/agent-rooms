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

    @Test @MainActor func resolving_requests_drains_the_inbox() async throws {
        let state = AppState()
        let initial = state.inboxCount
        #expect(initial > 0)
        state.resolveRequest(state.requests[0], feedback: "Approved")
        #expect(state.inboxCount == initial - 1)
        #expect(state.toast == "Approved")

        state.clearInbox()
        // Clearing is staggered (55ms per card) for the cascade animation.
        try await Task.sleep(nanoseconds: 700_000_000)
        #expect(state.inboxCount == 0)
        #expect(state.toast == "Inbox cleared")
    }

    @Test @MainActor func live_events_mark_new_until_stream_is_viewed() {
        let state = AppState()
        let initialCount = state.events.count
        state.selectedTab = .picture
        state.deliverNextLiveEvent()
        #expect(state.events.count == initialCount + 1)
        #expect(!state.newEventIDs.isEmpty)

        // Opening the stream shows the NEW markers; leaving clears them.
        state.selectedTab = .stream
        #expect(!state.newEventIDs.isEmpty)
        state.selectedTab = .picture
        #expect(state.newEventIDs.isEmpty)

        // Events arriving while the stream is in view are not marked.
        state.selectedTab = .stream
        state.deliverNextLiveEvent()
        #expect(state.newEventIDs.isEmpty)
    }

    @Test @MainActor func tray_actions_surface_toast_feedback() {
        let state = AppState()
        state.toggleLiveViewPinned()
        #expect(state.liveViewPinned)
        #expect(state.toast == "Live view pinned to The Picture")
        state.openInFullApp("Open PR")
        #expect(state.toast == "Open PR opened in the full app")
        state.selectRoom(state.availableRooms[1])
        #expect(state.toast?.contains("Switched to") == true)
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
