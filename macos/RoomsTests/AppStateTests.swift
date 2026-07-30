import Foundation
import Testing
import ArchAstroPlatform
@testable import Rooms

@Suite struct AppStateTests {
    @Test @MainActor func starts_with_web_aligned_network_content() {
        let state = AppState()
        if case .restoring = state.phase {} else {
            Issue.record("Expected initial phase to be .restoring")
        }
        #expect(!state.availableNetworks.isEmpty)
        #expect(!state.threads.isEmpty)
        #expect(!state.members.isEmpty)
        #expect(state.selectedTab == .chat)
        #expect(state.client == nil)
        #expect(!state.isSignedIn)
    }

    @Test @MainActor func network_and_thread_selection_are_explicit() {
        let state = AppState()
        state.selectNetwork(state.availableNetworks[1])
        #expect(state.selectedNetwork.id == state.availableNetworks[1].id)
        #expect(state.currentMembers.allSatisfy { $0.networkID == state.selectedNetwork.id })
        #expect(state.currentThreads.allSatisfy { $0.networkID == state.selectedNetwork.id })
        #expect(state.selectedThread.networkID == state.selectedNetwork.id)
        #expect(state.toast?.contains("Switched to") == true)
        state.selectNetwork(state.availableNetworks[0])
        state.selectThread(state.currentThreads[1])
        #expect(state.currentMessages.allSatisfy { $0.threadID == state.selectedThread.id })
        #expect(state.currentTasks.allSatisfy { $0.threadID == state.selectedThread.id })
    }

    @Test @MainActor func composer_requires_a_live_platform_session() async {
        let state = AppState()
        let sent = await state.sendMessage("Status is green")
        #expect(!sent)
    }

    @Test @MainActor func activity_marks_new_until_activity_is_left() {
        let state = AppState()
        let initialCount = state.events.count
        state.selectedTab = .chat
        state.deliverNextLiveEvent()
        #expect(state.events.count == initialCount + 1)
        #expect(!state.newEventIDs.isEmpty)
        state.selectedTab = .activity
        #expect(!state.newEventIDs.isEmpty)
        state.selectedTab = .chat
        #expect(state.newEventIDs.isEmpty)
    }

    @Test @MainActor func unseen_activity_is_scoped_per_network() {
        let state = AppState()
        state.selectedTab = .activity
        state.selectNetwork(state.availableNetworks[1])
        state.deliverNextLiveEvent()
        #expect(!state.newEventIDs.isEmpty)
        state.selectNetwork(state.availableNetworks[0])
        #expect(!state.newEventIDs.isEmpty)
        state.selectedTab = .chat
        #expect(state.newEventIDs.isEmpty)
    }

    @Test @MainActor func opening_threads_updates_canonical_unread_state() {
        let state = AppState()
        let initial = state.totalUnreadCount
        #expect(initial > 0)
        state.markSelectedThreadRead()
        #expect(state.totalUnreadCount < initial)
        state.selectThread(state.currentThreads[1])
        #expect(state.unreadCount(for: state.selectedNetwork.id) == 0)
    }

    @Test @MainActor func activity_navigation_does_not_consume_chat_unread() {
        let state = AppState()
        let target = state.availableNetworks[0]
        let unread = state.unreadCount(for: target.id)
        state.selectNetwork(state.availableNetworks[1])
        state.selectedTab = .activity
        state.selectNetwork(target)
        #expect(state.unreadCount(for: target.id) == unread)
    }

    @Test @MainActor func overlay_navigation_preserves_unseen_activity() {
        let state = AppState()
        state.selectedTab = .chat
        state.deliverNextLiveEvent()
        let unseen = state.newEventIDs
        state.selectNetwork(state.availableNetworks[0], markVisibleContentRead: false)
        state.selectedTab = .activity
        #expect(state.newEventIDs == unseen)
    }

    @Test @MainActor func overlay_navigation_reveals_event_without_marking_it_read() {
        let state = AppState()
        state.activityFilter = .error
        state.deliverNextLiveEvent()
        let event = state.events[0]
        let unseen = state.newEventIDs
        state.prepareActivityOverlay(event)
        #expect(state.activityFilter == .all)
        #expect(state.selectedNetwork.id == event.networkID)
        #expect(state.newEventIDs == unseen)
    }

    @Test @MainActor func activity_only_marks_visible_filter_results_read() {
        let state = AppState()
        state.newEventIDs = Set(state.currentEvents.map(\.id))
        state.activityFilter = .warning
        let warnings = Set(state.currentEvents.filter { $0.level == .warning }.map(\.id))
        state.selectedTab = .activity
        state.selectedTab = .chat
        #expect(state.newEventIDs.isDisjoint(with: warnings))
        #expect(!state.newEventIDs.isEmpty)
    }

    @Test @MainActor func changing_activity_filter_marks_the_previous_results_read() {
        let state = AppState()
        state.newEventIDs = Set(state.currentEvents.map(\.id))
        state.selectedTab = .activity
        state.activityFilter = .warning
        #expect(state.newEventIDs.isEmpty)
    }

    @Test @MainActor func filtered_live_activity_remains_unseen() {
        let state = AppState()
        state.selectedTab = .activity
        state.activityFilter = .error
        state.deliverNextLiveEvent()
        #expect(!state.newEventIDs.isEmpty)
    }

    @Test @MainActor func reselecting_network_preserves_thread() {
        let state = AppState()
        state.selectThread(state.currentThreads[1])
        let selected = state.selectedThread.id
        state.selectNetwork(state.selectedNetwork, markVisibleContentRead: false)
        #expect(state.selectedThread.id == selected)
    }

    @Test @MainActor func network_without_threads_clears_chat_context() async {
        let state = AppState()
        let empty = NetworkSnapshot(
            id: "net_empty",
            name: "Empty",
            relationship: "ArchAstro ↔ Empty",
            unreadCount: 0,
            hostOrganization: "ArchAstro",
            collaboratorOrganization: "Empty",
            slackChannel: nil
        )
        state.selectNetwork(empty)
        #expect(state.selectedThread.networkID == empty.id)
        #expect(state.selectedThread.id.isEmpty)
        #expect(state.currentMessages.isEmpty)
        #expect(state.currentTasks.isEmpty)
        let sent = await state.sendMessage("Keep this draft")
        #expect(!sent)
    }

    @Test @MainActor func base_url_defaults_to_production() {
        let state = AppState()
        #expect(state.baseURL.hasPrefix("https://"))
    }

    @Test @MainActor func web_handoffs_preserve_network_thread_and_drill_in() {
        let state = AppState()
        state.selectedTab = .activity
        let url = state.webAppURL(
            extraQueryItems: [URLQueryItem(name: "session", value: "ses_test")]
        )
        #expect(url?.path == "/teams/\(state.selectedNetwork.id)")
        let values = URLComponents(url: url!, resolvingAgainstBaseURL: false)?
            .queryItems?.reduce(into: [String: String]()) { $0[$1.name] = $1.value }
        #expect(values?["tab"] == "activity")
        #expect(values?["thread"] == state.selectedThread.id)
        #expect(values?["session"] == "ses_test")

        state.archagentsURL = "https://host.example/archagents/"
        #expect(state.webAppURL()?.path == "/archagents/teams/\(state.selectedNetwork.id)")
        UserDefaults.standard.removeObject(forKey: "archagentsURL")
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
            orgName: "Acme",
            appId: "dap_test",
            userId: "usr_test"
        )
        let data = try JSONEncoder().encode(session)
        let decoded = try JSONDecoder().decode(StoredSession.self, from: data)
        #expect(decoded.kind == .archagents)
        #expect(decoded.accessToken == "token")
        #expect(decoded.refreshToken == "refresh")
        #expect(decoded.orgName == "Acme")
        #expect(decoded.appId == "dap_test")
        #expect(decoded.userId == "usr_test")
        #expect(decoded.apiKey == nil)
    }
}

@Suite struct TeamRoomAPITests {
    @Test func initials_are_stable_for_people_agents_and_empty_names() {
        #expect(TeamRoomAPI.initials(for: "Calvin Giddings") == "CG")
        #expect(TeamRoomAPI.initials(for: "Fleet") == "F")
        #expect(TeamRoomAPI.initials(for: "") == "?")
    }

    @Test func relative_time_is_compact() {
        #expect(TeamRoomAPI.relativeTime(Date()) == "now")
        #expect(TeamRoomAPI.relativeTime(Date().addingTimeInterval(-3_700)) == "1h")
        #expect(TeamRoomAPI.relativeTime(nil as Date?) == "")
    }

    /// Opt-in production smoke used by maintainers. Normal CI skips it; a
    /// local authenticated run creates a mode-0600 temporary credential file
    /// and proves the exact SDK/mapping path the app ships.
    @Test func live_account_loads_its_real_team_rooms() async throws {
        struct Credentials: Decodable {
            var token: String
            var publishableKey: String
            var userID: String
            var appID: String
            var server: String
        }
        let url = URL(fileURLWithPath: "/tmp/rooms-live-smoke-current-user.json")
        guard let data = try? Data(contentsOf: url) else { return }
        let credentials = try JSONDecoder().decode(Credentials.self, from: data)

        let client = PlatformClient(
            baseUrl: credentials.server,
            accessToken: credentials.token,
            defaultHeaders: ["x-archastro-api-key": credentials.publishableKey]
        )
        defer { Task { await client.close() } }
        let me = try await client.users.me()
        #expect(me.id == credentials.userID)
        let rooms = try await TeamRoomAPI.load(
            client: client,
            currentUserID: credentials.userID,
            organizationName: "Live account"
        )
        #expect(!rooms.isEmpty)
        #expect(rooms.allSatisfy { !$0.threads.isEmpty })
        #expect(rooms.allSatisfy { $0.threads.allSatisfy { $0.title == "Team Room" } })
        #expect(rooms.contains { !$0.messages.isEmpty })

        let marker = "Rooms macOS live smoke \(UUID().uuidString)"
        let threadID = try #require(rooms.first?.threads.first?.id)
        try await TeamRoomAPI.post(
            client: client,
            appID: credentials.appID,
            userID: credentials.userID,
            threadID: threadID,
            content: marker
        )
        let updated = try await TeamRoomAPI.load(
            client: client,
            currentUserID: credentials.userID,
            organizationName: "Live account"
        )
        let smokeMessage = try #require(
            updated.flatMap(\.messages).first(where: { $0.body == marker })
        )
        try await client.threadMessages.delete(message: smokeMessage.id)
    }
}
