import Foundation
import Testing
import UserNotifications
@testable import Rooms

@Suite struct MentionNotificationCompletionHandlerTests {
    @Test func callbacks_can_run_outside_the_main_actor() async {
        await Task.detached {
            MentionNotificationCompletionHandlers.authorization(false, nil)
            MentionNotificationCompletionHandlers.delivery(nil)
        }.value
    }
}

@Suite struct MentionMatcherTests {
    private let identity = MentionIdentity(
        fullName: "Calvin Giddings",
        alias: "calvin-g",
        email: "calvin.giddings+rooms@example.com"
    )

    @Test func matches_first_last_full_name_and_supported_at_tags() {
        for text in [
            "Calvin, can you check this?",
            "Heads up GIDDINGS!",
            "Waiting on Calvin Giddings",
            "ping @calvin-g",
            "ping @calvin",
            "ping @giddings",
            "ping @calvin.giddings",
            "ping @calvingiddings",
            "ping @calvin_giddings",
        ] {
            #expect(MentionMatcher.matches(text, identity: identity), "\(text)")
        }
    }

    @Test func name_matching_is_case_insensitive_and_word_delimited() {
        #expect(MentionMatcher.matches("hey cÁlvin", identity: identity))
        #expect(!MentionMatcher.matches("calvinator is a project", identity: identity))
        #expect(!MentionMatcher.matches("ping @calvin-g-extra", identity: identity))
        #expect(!MentionMatcher.matches("sent to someone@calvin-g", identity: identity))
        #expect(!MentionMatcher.matches("nothing for this person", identity: identity))
    }

    @Test func an_empty_identity_never_matches() {
        #expect(
            !MentionMatcher.matches(
                "@calvin Calvin",
                identity: MentionIdentity()
            )
        )
    }
}

@Suite struct MessageMentionTests {
    @Test func notification_payload_round_trips_and_uses_a_stable_message_id() throws {
        let mention = MessageMention(
            target: MentionNavigationTarget(
                networkID: "tem_archastro",
                threadID: "thr_room",
                messageID: "msg_mention"
            ),
            roomName: "ArchAstro Team",
            threadName: "Team Room",
            author: "Vivek",
            body: "Calvin, take a look."
        )

        #expect(mention.requestIdentifier == "rooms.mention.msg_mention")
        #expect(MessageMention(userInfo: mention.userInfo) == mention)
        let content = mention.content()
        #expect(content.title == "Vivek mentioned you")
        #expect(content.subtitle == "ArchAstro Team · Team Room")
        #expect(content.body == "Calvin, take a look.")
        #expect(content.categoryIdentifier == MessageMention.categoryIdentifier)
        #expect(content.threadIdentifier == "thr_room")
    }

    @Test @MainActor func incoming_mentions_notify_once_and_never_notify_own_messages() {
        let state = AppState()
        state.userName = "Calvin Giddings"
        state.userAlias = "calvin-g"
        state.userEmail = "calvin@example.com"
        state.availableNetworks = [
            NetworkSnapshot(
                id: "tem_archastro",
                name: "ArchAstro Team",
                relationship: "Member",
                unreadCount: 0,
                hostOrganization: "ArchAstro",
                collaboratorOrganization: "Shared",
                slackChannel: nil
            )
        ]
        state.threads = [
            NetworkThread(
                id: "thr_room",
                networkID: "tem_archastro",
                title: "Team Room",
                isDefault: true,
                unreadCount: 0
            )
        ]
        var mentions: [MessageMention] = []
        state.onMention = { mentions.append($0) }

        let message = chatMessage(
            id: "msg_mention",
            body: "Hey @calvin-g, this needs you."
        )
        let event = streamEvent(messageID: message.id)
        state.announceIncomingMessage(message, event: event)
        state.announceIncomingMessage(message, event: event)
        state.announceIncomingMessage(
            chatMessage(
                id: "msg_own",
                body: "Calvin wrote this",
                isCurrentUser: true
            ),
            event: streamEvent(messageID: "msg_own")
        )
        state.announceIncomingMessage(
            chatMessage(id: "msg_other", body: "No mention here"),
            event: streamEvent(messageID: "msg_other")
        )

        #expect(mentions.count == 1)
        #expect(mentions.first?.target.messageID == "msg_mention")
        #expect(mentions.first?.roomName == "ArchAstro Team")
        #expect(mentions.first?.threadName == "Team Room")
    }

    @Test @MainActor func notification_navigation_selects_and_focuses_the_exact_message() {
        let state = AppState()
        let network = NetworkSnapshot(
            id: "tem_target",
            name: "Target Team",
            relationship: "Member",
            unreadCount: 1,
            hostOrganization: "ArchAstro",
            collaboratorOrganization: "Shared",
            slackChannel: nil
        )
        let thread = NetworkThread(
            id: "thr_target",
            networkID: network.id,
            title: "Team Room",
            isDefault: true,
            unreadCount: 1
        )
        state.availableNetworks = [network]
        state.threads = [thread]
        state.messages = [
            chatMessage(
                id: "msg_target",
                threadID: thread.id,
                body: "Calvin, this is the one."
            )
        ]
        state.selectedTab = .activity

        let revealed = state.prepareMentionNavigation(
            MentionNavigationTarget(
                networkID: network.id,
                threadID: thread.id,
                messageID: "msg_target"
            )
        )

        #expect(revealed)
        #expect(state.selectedNetwork.id == network.id)
        #expect(state.selectedThread.id == thread.id)
        #expect(state.selectedTab == .chat)
        #expect(state.messageFocus?.messageID == "msg_target")
    }

    @Test @MainActor func anchored_context_appends_after_the_newest_page() {
        let state = AppState()
        state.messages = [
            chatMessage(id: "msg_new", body: "Newest"),
        ]
        state.appendMessageContext(
            LoadedMessagePage(
                threadID: "thr_room",
                messages: [
                    chatMessage(id: "msg_target", body: "Calvin"),
                    chatMessage(id: "msg_old", body: "Older"),
                ],
                events: [],
                beforeCursor: "older-page",
                afterCursor: "newer-page"
            )
        )

        #expect(state.messages.map(\.id) == ["msg_new", "msg_target", "msg_old"])
        #expect(state.messageHistoryByThread["thr_room"]?.beforeCursor == "older-page")
    }

    private func chatMessage(
        id: String,
        threadID: String = "thr_room",
        body: String,
        isCurrentUser: Bool = false
    ) -> ChatMessage {
        ChatMessage(
            id: id,
            threadID: threadID,
            author: "Vivek",
            initials: "V",
            organization: "ArchAstro",
            body: body,
            time: "now",
            isCurrentUser: isCurrentUser,
            agentMode: nil,
            attachments: []
        )
    }

    private func streamEvent(messageID: String) -> StreamEvent {
        StreamEvent(
            id: "event-\(messageID)",
            networkID: "tem_archastro",
            level: .info,
            author: "Vivek",
            body: "Update",
            time: "now",
            sessionID: messageID
        )
    }
}
