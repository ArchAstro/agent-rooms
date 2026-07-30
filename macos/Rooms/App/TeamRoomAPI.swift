import Foundation
import ArchAstroPlatform

/// A fully hydrated Team Room. The app deliberately maps platform models at
/// this boundary so the SwiftUI layer never depends on generated API shapes.
struct LoadedTeamRoom: Sendable {
    var room: NetworkSnapshot
    var members: [NetworkMember]
    var threads: [NetworkThread]
    var messages: [ChatMessage]
    var events: [StreamEvent]
    var workstream: [WorkstreamItem]
}

struct TeamRoomMessageInput: Codable, Sendable {
    var content: String
    var user: String
}

enum TeamRoomAPIError: LocalizedError {
    case tooManyTeamPages
    case cannotPost

    var errorDescription: String? {
        switch self {
        case .tooManyTeamPages:
            "Rooms could not safely load every team membership page."
        case .cannotPost:
            "This saved session can read rooms but cannot post. Sign in again to refresh it."
        }
    }
}

enum TeamRoomAPI {
    private struct TeamPage: Decodable, Sendable {
        var data: [TeamDTO]
        var hasNext: Bool

        enum CodingKeys: String, CodingKey {
            case data
            case hasNext = "has_next"
        }
    }

    private struct TeamDTO: Decodable, Sendable {
        var id: String
        var name: String?
        var membershipStatus: String?

        enum CodingKeys: String, CodingKey {
            case id, name
            case membershipStatus = "membership_status"
        }
    }

    private struct ThreadEnvelope: Decodable, Sendable {
        var data: [ThreadDTO]
    }

    private struct ThreadDTO: Decodable, Sendable {
        var id: String
        var title: String?
        var isDefault: Bool?
        var unreadCount: Int?

        enum CodingKeys: String, CodingKey {
            case id, title
            case isDefault = "is_default"
            case unreadCount = "unread_count"
        }
    }

    private struct MemberEnvelope: Decodable, Sendable {
        var data: [MemberDTO]
    }

    private struct MemberDTO: Decodable, Sendable {
        var id: String
        var joinedAt: String?
        var name: String?
        var role: String?
        var type: String?
        var user: UserDTO?
        var agent: AgentDTO?

        enum CodingKeys: String, CodingKey {
            case id, name, role, type, user, agent
            case joinedAt = "joined_at"
        }
    }

    private struct UserDTO: Decodable, Sendable {
        var id: String
        var name: String?
        var email: String?
        var orgName: String?

        enum CodingKeys: String, CodingKey {
            case id, name, email
            case orgName = "org_name"
        }
    }

    private struct AgentDTO: Decodable, Sendable {
        var id: String
        var name: String?
    }

    struct MessageEnvelope: Decodable, Sendable {
        var data: MessagePage
    }

    struct MessagePage: Decodable, Sendable {
        var messages: [MessageDTO]
    }

    struct MessageDTO: Decodable, Sendable {
        struct ActorDTO: Decodable, Sendable {
            var id: String?
            var name: String?
            var alias: String?
        }

        struct AttachmentDTO: Decodable, Sendable {
            struct ImageSourceDTO: Decodable, Sendable {
                var url: String?
            }

            var id: String
            var type: String
            var filename: String?
            var contentType: String?
            var url: String?
            var title: String?
            var description: String?
            var imageURL: String?
            var imageSource: ImageSourceDTO?
            var width: Int?
            var height: Int?
            var imageWidth: Int?
            var imageHeight: Int?
            var version: Int?
            var name: String?
            var mediaType: String?
            var status: String?
            var object: JSONValue?

            enum CodingKeys: String, CodingKey {
                case id, type, filename, url, title, description, width, height
                case version, name, status, object
                case contentType = "content_type"
                case imageURL = "image_url"
                case imageSource = "image_source"
                case imageWidth = "image_width"
                case imageHeight = "image_height"
                case mediaType = "media_type"
            }
        }

        var actors: [ActorDTO]?
        var agent: String?
        var agentMode: String?
        var attachments: [AttachmentDTO]?
        var content: String?
        var createdAt: String?
        var id: String
        var metadata: [String: JSONValue]?
        var thread: String?

        enum CodingKeys: String, CodingKey {
            case actors, agent, attachments, content, id, metadata, thread
            case agentMode = "agent_mode"
            case createdAt = "created_at"
        }
    }

    static func load(
        client: PlatformClient,
        currentUserID: String?,
        organizationName: String?
    ) async throws -> [LoadedTeamRoom] {
        let teams = try await joinedTeams(client: client)
        var loaded: [LoadedTeamRoom] = []

        for team in teams {
            let threadEnvelope: ThreadEnvelope = try await client.http.request(
                "/api/v1/teams/\(team.id)/threads"
            )
            let teamThreads = threadEnvelope.data
            let roomThreads = teamThreads.filter {
                ($0.title ?? "").localizedCaseInsensitiveCompare("Team Room") == .orderedSame
            }
            guard !roomThreads.isEmpty else { continue }

            let memberResponse: MemberEnvelope = try await client.http.request(
                "/api/v1/teams/\(team.id)/members"
            )
            let roomMembers = memberResponse.data.map { membership in
                let name = membership.name
                    ?? membership.user?.name
                    ?? membership.user?.email
                    ?? membership.agent?.name
                    ?? "Team member"
                let memberID = membership.user?.id
                    ?? membership.agent?.id
                    ?? membership.id
                let kind: NetworkMember.Kind = membership.type == "agent" ? .agent : .user
                return NetworkMember(
                    id: "\(team.id)-\(memberID)",
                    networkID: team.id,
                    name: name,
                    initials: initials(for: name),
                    kind: kind,
                    role: (membership.role ?? "member").capitalized,
                    organization: membership.user?.orgName ?? organizationName ?? "Team",
                    joined: relativeTime(membership.joinedAt),
                    presence: .active
                )
            }

            var mappedThreads: [NetworkThread] = []
            var mappedMessages: [ChatMessage] = []
            var mappedEvents: [StreamEvent] = []
            var mappedWorkstream: [WorkstreamItem] = []

            for thread in roomThreads {
                mappedThreads.append(
                    NetworkThread(
                        id: thread.id,
                        networkID: team.id,
                        title: thread.title ?? "Team Room",
                        isDefault: thread.isDefault ?? true,
                        unreadCount: thread.unreadCount ?? 0
                    )
                )

                let response: MessageEnvelope = try await client.http.request(
                    "/api/v1/threads/\(thread.id)/messages",
                    query: [("limit", "100")]
                )
                let messages = response.data.messages.map {
                    mapMessage($0, currentUserID: currentUserID)
                }
                mappedMessages.append(contentsOf: messages)
                mappedEvents.append(contentsOf: response.data.messages.reversed().map {
                    mapEvent($0, networkID: team.id)
                })

                if let latest = messages.last {
                    mappedWorkstream.append(
                        WorkstreamItem(
                            id: "work-\(thread.id)",
                            networkID: team.id,
                            kind: .thread,
                            title: thread.title ?? "Team Room",
                            detail: "\(messages.count) recent updates · latest from \(latest.author)",
                            time: latest.time
                        )
                    )
                }
            }

            let count = roomMembers.count
            let role = team.membershipStatus?.capitalized ?? "Member"
            loaded.append(
                LoadedTeamRoom(
                    room: NetworkSnapshot(
                        id: team.id,
                        name: team.name ?? "Team Room",
                        relationship: "\(role) · \(count) \(count == 1 ? "member" : "members")",
                        unreadCount: mappedThreads.reduce(0) { $0 + $1.unreadCount },
                        hostOrganization: organizationName ?? "Your organization",
                        collaboratorOrganization: "Shared Team Room",
                        slackChannel: nil
                    ),
                    members: roomMembers,
                    threads: mappedThreads,
                    messages: mappedMessages,
                    events: mappedEvents,
                    workstream: mappedWorkstream
                )
            )
        }
        return loaded
    }

    static func post(
        client: PlatformClient,
        appID: String?,
        userID: String?,
        threadID: String,
        content: String
    ) async throws {
        guard let appID, let userID else { throw TeamRoomAPIError.cannotPost }
        let _: JSONValue = try await client.http.request(
            "/protected/api/v1/developer/apps/\(appID)/threads/\(threadID)/messages",
            method: "POST",
            body: TeamRoomMessageInput(content: content, user: userID)
        )
    }

    private static func joinedTeams(client: PlatformClient) async throws
        -> [TeamDTO]
    {
        var teams: [TeamDTO] = []
        for page in 1...20 {
            let response: TeamPage = try await client.http.request(
                "/api/v1/teams",
                query: [
                    ("page", String(page)),
                    ("page_size", "100"),
                    ("membership", "joined"),
                ]
            )
            teams.append(contentsOf: response.data)
            if !response.hasNext { return teams }
        }
        throw TeamRoomAPIError.tooManyTeamPages
    }

    static func mapMessage(
        _ message: MessageDTO,
        currentUserID: String?
    ) -> ChatMessage {
        let actor = message.actors?.first
        let author = actor?.name ?? actor?.alias ?? (message.agent == nil ? "Teammate" : "Agent")
        let actorID = actor?.id ?? ""
        let isCurrentUser = currentUserID.map {
            actorID == "user-\($0)"
        } ?? false
        return ChatMessage(
            id: message.id,
            threadID: message.thread ?? "",
            author: author,
            initials: initials(for: author),
            organization: isCurrentUser ? "You" : "",
            body: message.content ?? "",
            time: relativeTime(message.createdAt),
            isCurrentUser: isCurrentUser,
            agentMode: message.agentMode,
            attachments: message.attachments?.map {
                ChatAttachment(
                    id: $0.id,
                    type: $0.type,
                    filename: $0.filename,
                    contentType: $0.contentType,
                    url: $0.url,
                    title: $0.title,
                    description: $0.description,
                    imageURL: $0.imageURL,
                    imageSourceURL: $0.imageSource?.url,
                    width: $0.width ?? $0.imageWidth,
                    height: $0.height ?? $0.imageHeight,
                    version: $0.version,
                    name: $0.name,
                    mediaType: $0.mediaType,
                    status: $0.status,
                    object: $0.object
                )
            } ?? []
        )
    }

    private static func mapEvent(
        _ message: MessageDTO,
        networkID: String
    ) -> StreamEvent {
        let actor = message.actors?.first
        let author = actor?.name ?? actor?.alias ?? (message.agent == nil ? "Teammate" : "Agent")
        let content = message.content ?? "Shared an attachment"
        return StreamEvent(
            id: "event-\(message.id)",
            networkID: networkID,
            level: level(for: content),
            author: author,
            body: content,
            time: relativeTime(message.createdAt),
            sessionID: metadataString(message.metadata, key: "session_id")
                ?? metadataString(message.metadata, key: "codex_session_id")
                ?? message.id
        )
    }

    private static func level(for content: String) -> StreamEvent.Level {
        if content.hasPrefix("⚠") { return .warning }
        if content.hasPrefix("✗") { return .error }
        if content.hasPrefix("✓") { return .audit }
        if content.hasPrefix("▶") || content.hasPrefix("→") || content.hasPrefix("?") {
            return .info
        }
        return .info
    }

    private static func metadataString(
        _ metadata: [String: JSONValue]?,
        key: String
    ) -> String? {
        metadata?[key]?.stringValue
    }

    static func initials(for name: String) -> String {
        let parts = name.split(separator: " ").prefix(2)
        let value = parts.compactMap(\.first).map(String.init).joined()
        return value.isEmpty ? "?" : value.uppercased()
    }

    static func relativeTime(_ date: Date?) -> String {
        guard let date else { return "" }
        let seconds = max(0, Int(Date().timeIntervalSince(date)))
        if seconds < 60 { return "now" }
        if seconds < 3_600 { return "\(seconds / 60)m" }
        if seconds < 86_400 { return "\(seconds / 3_600)h" }
        return "\(seconds / 86_400)d"
    }

    static func relativeTime(_ raw: String?) -> String {
        guard var raw, !raw.isEmpty else { return "" }
        // The platform historically emitted both strict RFC 3339 and naive
        // UTC timestamps. Accept both at this boundary.
        if !raw.hasSuffix("Z")
            && raw.range(of: #"[+-]\d{2}:\d{2}$"#, options: .regularExpression) == nil
        {
            raw += "Z"
        }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = formatter.date(from: raw)
            ?? {
                formatter.formatOptions = [.withInternetDateTime]
                return formatter.date(from: raw)
            }()
        return relativeTime(date)
    }
}
