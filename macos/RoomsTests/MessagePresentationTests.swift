import Foundation
import Testing
import ArchAstroPlatform
@testable import Rooms

@Suite struct MessagePresentationTests {
    @Test func room_post_protocol_lines_get_native_presentation() throws {
        let parsed = try #require(
            RoomPostPresentation.parse(
                """
                ✓ Calvin (rich-message-parity): ✓ Markdown and task cards now render.
                - **GFM** tables stay readable
                - [PR](https://example.com)
                """
            )
        )

        #expect(parsed.kind == .done)
        #expect(parsed.author == "Calvin")
        #expect(parsed.tag == "rich-message-parity")
        #expect(parsed.body.hasPrefix("Markdown and task cards now render."))
        #expect(parsed.body.contains("**GFM**"))
    }

    @Test func ordinary_glyph_led_dialogue_stays_dialogue() {
        #expect(RoomPostPresentation.parse("? should we ship this?") == nil)
        #expect(RoomPostPresentation.parse("✓ this is just prose") == nil)
        #expect(RoomPostPresentation.parse("plain message") == nil)
    }

    @Test func copied_message_text_matches_the_rendered_markdown() {
        let copied = MessageText.plainText(
            "**Ready** with [evidence](https://example.com) and `code`."
        )

        #expect(copied == "Ready with evidence and code.")
    }

    @Test func message_wire_maps_every_rich_attachment_field() throws {
        let data = Data(
            """
            {
              "data": {
                "messages": [{
                  "id": "msg_rich",
                  "thread": "thr_room",
                  "content": "Here are the results",
                  "agent_mode": "embedded",
                  "created_at": "2026-07-29T20:00:00Z",
                  "actors": [{"id": "user-usr_me", "name": "Calvin"}],
                  "attachments": [
                    {
                      "id": "fil_image",
                      "type": "file",
                      "filename": "result.png",
                      "content_type": "image/png",
                      "url": "https://example.com/result.png",
                      "image_source": {"url": "https://example.com/result-small.png"},
                      "width": 1200,
                      "height": 800
                    },
                    {
                      "id": "tsk_launch",
                      "type": "task",
                      "title": "Ship the app",
                      "description": "Verify the signed build",
                      "object": {
                        "status": "in_progress",
                        "due_date": "2026-07-31T00:00:00Z",
                        "subtasks_count": 2,
                        "owner_actor": {
                          "name": "Fleet",
                          "profile_picture": {"url": "https://example.com/fleet.png"}
                        }
                      }
                    },
                    {
                      "id": "art_evidence",
                      "type": "artifact",
                      "title": "PR evidence",
                      "version": 3,
                      "content_type": "application/json",
                      "url": "https://example.com/evidence.json"
                    },
                    {
                      "id": "lnk_docs",
                      "type": "scraped_link",
                      "title": "Rooms docs",
                      "description": "The app guide",
                      "url": "https://example.com/docs",
                      "image_url": "https://example.com/preview.png",
                      "image_width": 640,
                      "image_height": 360
                    }
                  ]
                }]
              }
            }
            """.utf8
        )

        let envelope = try JSONCoding.decoder.decode(
            ThreadMessagesResponse.self,
            from: data
        )
        let message = TeamRoomAPI.mapMessage(
            try #require(envelope.data.messages.first),
            currentUserID: "usr_me"
        )

        #expect(message.isCurrentUser)
        #expect(message.agentMode == "embedded")
        #expect(message.attachments.count == 4)

        let image = try #require(message.attachments.first)
        #expect(image.isImage)
        #expect(image.displayName == "result.png")
        #expect(image.width == 1200)
        #expect(image.imageSourceURL == "https://example.com/result-small.png")

        let task = try #require(message.attachments[1].task)
        #expect(task.name == "Ship the app")
        #expect(task.status == "in_progress")
        #expect(task.ownerName == "Fleet")
        #expect(task.subtasksCount == 2)

        let artifact = message.attachments[2]
        #expect(artifact.version == 3)
        #expect(artifact.resolvedURL?.absoluteString == "https://example.com/evidence.json")

        let link = message.attachments[3]
        #expect(link.width == 640)
        #expect(link.height == 360)
        #expect(link.imageURL == "https://example.com/preview.png")
    }

    @Test func message_pages_keep_cursors_and_present_newest_first() throws {
        let data = Data(
            """
            {
              "data": {
                "messages": [
                  {"id": "msg_1", "thread": "thr_room", "content": "Oldest"},
                  {"id": "msg_2", "thread": "thr_room", "content": "Middle"},
                  {"id": "msg_3", "thread": "thr_room", "content": "Newest"}
                ],
                "before_cursor": "older-page",
                "after_cursor": null
              }
            }
            """.utf8
        )

        let envelope = try JSONCoding.decoder.decode(
            ThreadMessagesResponse.self,
            from: data
        )
        let page = TeamRoomAPI.mapMessagePage(
            envelope.data,
            threadID: "thr_room",
            networkID: "team_room",
            currentUserID: nil
        )

        #expect(TeamRoomAPI.messagePageSize == 20)
        #expect(page.messages.map(\.id) == ["msg_3", "msg_2", "msg_1"])
        #expect(page.events.map(\.id) == [
            "event-msg_3",
            "event-msg_2",
            "event-msg_1",
        ])
        #expect(page.beforeCursor == "older-page")
        #expect(page.afterCursor == nil)
    }

    @Test func generated_channel_messages_use_the_same_presentation_mapping() throws {
        let payload = try JSONCoding.decoder.decode(
            ApiChatMessageAddedPayload.self,
            from: Data(
                """
                {
                  "thread_id": "thr_room",
                  "before_cursor": "before-live",
                  "message": {
                    "id": "msg_live",
                    "thread": "thr_room",
                    "content": "Live from Channel",
                    "created_at": "2026-07-29T20:00:00Z",
                    "actors": [{"id": "user-usr_me", "name": "Calvin"}],
                    "attachments": []
                  }
                }
                """.utf8
            )
        )

        let mapped = try #require(
            TeamRoomAPI.mapRealtimeMessage(
                payload,
                networkID: "team_room",
                currentUserID: "usr_me"
            )
        )
        #expect(mapped.message.id == "msg_live")
        #expect(mapped.message.threadID == "thr_room")
        #expect(mapped.message.isCurrentUser)
        #expect(mapped.event.id == "event-msg_live")
    }

    @Test func channel_join_metadata_maps_users_and_agents_without_timestamp_dtos() throws {
        let response: JSONValue = [
            "data": [
                "metadata": [
                    "members": [
                        [
                            "type": "user",
                            "user_id": "usr_calvin",
                            "membership_type": "owner",
                            "user": [
                                "id": "usr_calvin",
                                "name": "Calvin",
                                "org_name": "ArchAstro",
                            ],
                        ],
                        [
                            "type": "agent",
                            "agent_id": "agi_fleet",
                            "membership_type": "member",
                            "agent": [
                                "id": "agi_fleet",
                                "name": "Fleet",
                                "org_name": "ArchAstro",
                            ],
                        ],
                    ]
                ]
            ]
        ]

        let members = TeamRoomAPI.mapChannelMembers(
            joinResponse: response,
            networkID: "team_room",
            organizationName: nil
        )

        #expect(members.map(\.name) == ["Calvin", "Fleet"])
        #expect(members.map(\.kind) == [.user, .agent])
        #expect(members.map(\.role) == ["Owner", "Member"])
    }

    @Test func chart_payloads_cover_every_web_chart_family() throws {
        for kind in ["bars", "line", "area", "composed"] {
            let chart = try #require(
                ChatChart(
                    object: [
                        "title": "Velocity",
                        "spec": [
                            "kind": .string(kind),
                            "categories": ["Mon", "Tue"],
                            "series": [
                                [
                                    "name": "Merged",
                                    "values": [2, 5],
                                    "as": "line",
                                    "axis": "right",
                                ]
                            ],
                        ],
                    ]
                )
            )
            guard case .series(let parsedKind, let title, _, let categories, let series) = chart else {
                Issue.record("Expected a series chart for \(kind)")
                continue
            }
            #expect(parsedKind.rawValue == kind)
            #expect(title == "Velocity")
            #expect(categories == ["Mon", "Tue"])
            #expect(series.first?.values == [2, 5])
        }

        for kind in ["pie", "treemap"] {
            let chart = try #require(
                ChatChart(
                    object: [
                        "spec": [
                            "kind": .string(kind),
                            "cells": [
                                ["name": "Rooms", "size": 7, "heat": 0.8],
                                ["name": "Web", "size": 3],
                            ],
                        ]
                    ]
                )
            )
            guard case .cells(let parsedKind, _, let cells) = chart else {
                Issue.record("Expected a cell chart for \(kind)")
                continue
            }
            #expect(parsedKind.rawValue == kind)
            #expect(cells.count == 2)
        }

        let scatter = try #require(
            ChatChart(
                object: [
                    "spec": [
                        "kind": "scatter",
                        "xLabel": "Latency",
                        "yLabel": "Success",
                        "groups": [
                            [
                                "name": "Runs",
                                "points": [
                                    ["x": 1.5, "y": 99.0],
                                    ["x": 2.0, "y": 98.5],
                                ],
                            ]
                        ],
                    ]
                ]
            )
        )
        guard case .scatter(_, let xLabel, let yLabel, let groups) = scatter else {
            Issue.record("Expected a scatter chart")
            return
        }
        #expect(xLabel == "Latency")
        #expect(yLabel == "Success")
        #expect(groups.first?.points.count == 2)
    }

    @Test func malformed_charts_fall_back_instead_of_crashing_the_message() {
        let missingValues: JSONValue = [
            "spec": [
                "kind": "bars",
                "categories": ["Mon"],
                "series": [["name": "Broken"]],
            ]
        ]
        let nonFiniteData: JSONValue = [
            "spec": [
                "kind": "scatter",
                "groups": [],
            ]
        ]
        let partiallyInvalid: JSONValue = [
            "spec": [
                "kind": "pie",
                "cells": [
                    ["name": "Valid", "size": 1],
                    ["name": "Invalid", "size": "large"],
                ],
            ]
        ]

        #expect(ChatChart(object: missingValues) == nil)
        #expect(ChatChart(object: nonFiniteData) == nil)
        #expect(ChatChart(object: partiallyInvalid) == nil)
    }

    @Test func future_attachment_types_remain_visible_as_generic_cards() {
        let attachment = ChatAttachment(id: "new_1", type: "native_template")
        #expect(attachment.displayName == "Native Template")
        #expect(!attachment.isImage)
        #expect(attachment.chart == nil)
        #expect(attachment.task == nil)

        let unsafe = ChatAttachment(
            id: "file_unsafe",
            type: "file",
            url: "javascript:alert(1)"
        )
        #expect(unsafe.resolvedURL == nil)
    }
}
