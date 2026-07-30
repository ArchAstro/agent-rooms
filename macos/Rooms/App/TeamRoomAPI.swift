import Foundation
import ArchAstroPlatform

/// An initially hydrated Team Room. The app deliberately maps platform models
/// at this boundary so SwiftUI receives a bounded first message page and never
/// depends on generated API shapes.
struct LoadedTeamRoom: Sendable {
    var room: NetworkSnapshot
    var members: [NetworkMember]
    var threads: [NetworkThread]
    var messages: [ChatMessage]
    var messageHistories: [ThreadMessageHistory]
    var events: [StreamEvent]
    var workstream: [WorkstreamItem]
}

struct ThreadMessageHistory: Sendable, Equatable {
    var threadID: String
    var beforeCursor: String?
}

struct LoadedMessagePage: Sendable {
    var threadID: String
    var messages: [ChatMessage]
    var events: [StreamEvent]
    var beforeCursor: String?
    var afterCursor: String?
}

struct LoadedRealtimeMessage: Sendable {
    var message: ChatMessage
    var event: StreamEvent
}

enum TeamRoomAPIError: LocalizedError {
    case tooManyTeamPages

    var errorDescription: String? {
        switch self {
        case .tooManyTeamPages:
            "Rooms could not safely load every team membership page."
        }
    }
}

enum TeamRoomAPI {
    static let messagePageSize = 20

    static func load(
        client: PlatformClient,
        currentUserID: String?,
        organizationName: String?
    ) async throws -> [LoadedTeamRoom] {
        let teams = try await joinedTeams(client: client)
        return try await withThrowingTaskGroup(
            of: (Int, LoadedTeamRoom?).self
        ) { group in
            var nextTeamIndex = 0
            let concurrentTeamLimit = min(6, teams.count)

            func addTeam(at index: Int) {
                let team = teams[index]
                group.addTask {
                    (
                        index,
                        try await load(
                            team: team,
                            client: client,
                            currentUserID: currentUserID,
                            organizationName: organizationName
                        )
                    )
                }
            }

            for _ in 0..<concurrentTeamLimit {
                addTeam(at: nextTeamIndex)
                nextTeamIndex += 1
            }

            var loaded: [(Int, LoadedTeamRoom)] = []
            while let (index, room) = try await group.next() {
                if let room {
                    loaded.append((index, room))
                }
                if nextTeamIndex < teams.count {
                    addTeam(at: nextTeamIndex)
                    nextTeamIndex += 1
                }
            }
            return loaded.sorted { $0.0 < $1.0 }.map(\.1)
        }
    }

    static func loadMessagePage(
        client: PlatformClient,
        threadID: String,
        networkID: String,
        currentUserID: String?,
        beforeCursor: String? = nil,
        limit: Int = messagePageSize
    ) async throws -> LoadedMessagePage {
        let response = try await client.threads.messages(
            thread: threadID,
            beforeCursor: beforeCursor,
            limit: min(max(limit, 1), 100)
        )
        return mapMessagePage(
            response.data,
            threadID: threadID,
            networkID: networkID,
            currentUserID: currentUserID
        )
    }

    static func mapMessagePage(
        _ page: ThreadMessagesResponseData,
        threadID: String,
        networkID: String,
        currentUserID: String?
    ) -> LoadedMessagePage {
        // The server returns each page oldest-first. The Mac room is a
        // newest-first feed, so reverse once at the API boundary and append
        // older pages at the bottom.
        let newestFirst = page.messages.reversed()
        return LoadedMessagePage(
            threadID: threadID,
            messages: newestFirst.map {
                mapMessage($0, currentUserID: currentUserID)
            },
            events: newestFirst.map {
                mapEvent($0, networkID: networkID)
            },
            beforeCursor: page.beforeCursor,
            afterCursor: page.afterCursor
        )
    }

    private static func load(
        team: TeamListResponseDataItem,
        client: PlatformClient,
        currentUserID: String?,
        organizationName: String?
    ) async throws -> LoadedTeamRoom? {
        let threadEnvelope = try await client.teams.threads.list(team: team.id)
        let roomThreads = threadEnvelope.data.filter {
            ($0.title ?? "").localizedCaseInsensitiveCompare("Team Room") == .orderedSame
        }
        guard !roomThreads.isEmpty else { return nil }

        var mappedThreads: [NetworkThread] = []
        var mappedMessages: [ChatMessage] = []
        var mappedHistories: [ThreadMessageHistory] = []
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

            let page = try await loadMessagePage(
                client: client,
                threadID: thread.id,
                networkID: team.id,
                currentUserID: currentUserID
            )
            mappedMessages.append(contentsOf: page.messages)
            mappedEvents.append(contentsOf: page.events)
            mappedHistories.append(
                ThreadMessageHistory(
                    threadID: thread.id,
                    beforeCursor: page.beforeCursor
                )
            )

            if let latest = page.messages.first {
                let countLabel = page.beforeCursor == nil
                    ? "\(page.messages.count)"
                    : "\(page.messages.count)+"
                mappedWorkstream.append(
                    WorkstreamItem(
                        id: "work-\(thread.id)",
                        networkID: team.id,
                        kind: .thread,
                        title: thread.title ?? "Team Room",
                        detail: "\(countLabel) updates · latest from \(latest.author)",
                        time: latest.time
                    )
                )
            }
        }

        let role = team.membershipStatus?.capitalized ?? "Member"
        return LoadedTeamRoom(
            room: NetworkSnapshot(
                id: team.id,
                name: team.name ?? "Team Room",
                relationship: "\(role) · Live Team Room",
                unreadCount: mappedThreads.reduce(0) { $0 + $1.unreadCount },
                hostOrganization: organizationName ?? "Your organization",
                collaboratorOrganization: "Shared Team Room",
                slackChannel: nil
            ),
            // The SDK Channel join includes the room's polymorphic user/agent
            // member list without forcing the REST membership timestamp model.
            // RoomChannelSession installs those members immediately after join.
            members: [],
            threads: mappedThreads,
            messages: mappedMessages,
            messageHistories: mappedHistories,
            events: mappedEvents,
            workstream: mappedWorkstream
        )
    }

    static func mapChannelMembers(
        joinResponse: JSONValue?,
        networkID: String,
        organizationName: String?
    ) -> [NetworkMember] {
        let data = joinResponse?["data"]
        let metadata = data?["metadata"]
            ?? data?["chunk"]?["metadata"]
        guard let rawMembers = metadata?["members"]?.arrayValue else { return [] }

        return rawMembers.compactMap { raw in
            guard let object = raw.objectValue else { return nil }
            let type = object["type"]?.stringValue ?? "user"
            let principal = type == "agent"
                ? object["agent"]?.objectValue
                : object["user"]?.objectValue
            let principalID = object[type == "agent" ? "agent_id" : "user_id"]?.stringValue
                ?? principal?["id"]?.stringValue
            guard let principalID else { return nil }
            let name = principal?["name"]?.stringValue
                ?? principal?["email"]?.stringValue
                ?? (type == "agent" ? "Agent" : "Team member")
            return NetworkMember(
                id: "\(networkID)-\(principalID)",
                networkID: networkID,
                name: name,
                initials: initials(for: name),
                kind: type == "agent" ? .agent : .user,
                role: (
                    object["membership_type"]?.stringValue
                        ?? object["role"]?.stringValue
                        ?? "member"
                ).capitalized,
                organization: principal?["org_name"]?.stringValue
                    ?? organizationName
                    ?? "Team",
                joined: "",
                presence: .active
            )
        }
    }

    private static func joinedTeams(client: PlatformClient) async throws
        -> [TeamListResponseDataItem]
    {
        var teams: [TeamListResponseDataItem] = []
        for page in 1...20 {
            let response = try await client.teams.list(
                page: page,
                pageSize: 100,
                membership: "joined"
            )
            teams.append(contentsOf: response.data)
            if !response.hasNext { return teams }
        }
        throw TeamRoomAPIError.tooManyTeamPages
    }

    static func mapMessage(
        _ message: ThreadMessagesResponseDataMessagesItem,
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
                    imageURL: $0.imageUrl,
                    imageSourceURL: $0.imageSource?.url,
                    width: $0.width ?? $0.imageWidth,
                    height: $0.height ?? $0.imageHeight,
                    version: $0.version,
                    name: $0.name,
                    mediaType: $0.mediaType,
                    status: nil,
                    object: $0.object.map(JSONValue.object)
                )
            } ?? []
        )
    }

    static func mapRealtimeMessage(
        _ payload: ApiChatMessageAddedPayload,
        networkID: String,
        currentUserID: String?
    ) -> LoadedRealtimeMessage? {
        guard let message = payload.message else { return nil }
        return mapRealtimeMessage(
            message,
            fallbackThreadID: payload.threadId,
            networkID: networkID,
            currentUserID: currentUserID
        )
    }

    static func mapRealtimeMessage(
        _ payload: ApiChatMessageUpdatedPayload,
        networkID: String,
        currentUserID: String?
    ) -> LoadedRealtimeMessage? {
        guard let message = payload.message else { return nil }
        return mapRealtimeMessage(
            message,
            fallbackThreadID: payload.threadId,
            networkID: networkID,
            currentUserID: currentUserID
        )
    }

    /// Channel and REST message schemas are generated from the same platform
    /// contract but have operation-specific Swift names. Re-decode through the
    /// SDK's shared JSON codec so presentation mapping has one source of truth.
    private static func mapRealtimeMessage(
        _ message: some Encodable,
        fallbackThreadID: String?,
        networkID: String,
        currentUserID: String?
    ) -> LoadedRealtimeMessage? {
        guard
            let json = try? JSONValue(encodable: message),
            var sdkMessage = try? json.decode(
                ThreadMessagesResponseDataMessagesItem.self
            )
        else { return nil }
        if sdkMessage.thread == nil {
            sdkMessage.thread = fallbackThreadID
        }
        return LoadedRealtimeMessage(
            message: mapMessage(sdkMessage, currentUserID: currentUserID),
            event: mapEvent(sdkMessage, networkID: networkID)
        )
    }

    private static func mapEvent(
        _ message: ThreadMessagesResponseDataMessagesItem,
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
