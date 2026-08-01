import Foundation
import ArchAstroPlatform

enum RoomChannelEvent: Sendable {
    case messageAdded(networkID: String, ApiChatMessageAddedPayload)
    case messageUpdated(networkID: String, ApiChatMessageUpdatedPayload)
    case threadEvent(networkID: String, ApiChatThreadEventPayload)
    case typing(ApiChatTypingPayload)
}

enum RoomChannelSessionError: LocalizedError {
    case unavailable(String)
    case rejected(String)

    var errorDescription: String? {
        switch self {
        case .unavailable(let threadID):
            "The live channel for \(threadID) is not connected."
        case .rejected(let reason):
            reason
        }
    }
}

/// One SDK socket with a generated `ApiChatChannel` subscription for every
/// Team Room thread. REST remains responsible only for discovery and history;
/// live messages and chat mutations flow through these channels.
final class RoomChannelSession: @unchecked Sendable {
    let threadIDs: Set<String>
    let members: [NetworkMember]

    private let socket: Socket
    private let channelsByThreadID: [String: ApiChatChannel]
    private let unsubscribeHandlers: [@Sendable () -> Void]

    var isConnected: Bool {
        socket.isConnected
            && channelsByThreadID.values.allSatisfy(\.channel.isJoined)
    }

    private init(
        socket: Socket,
        channelsByThreadID: [String: ApiChatChannel],
        members: [NetworkMember],
        unsubscribeHandlers: [@Sendable () -> Void]
    ) {
        self.socket = socket
        self.channelsByThreadID = channelsByThreadID
        self.members = members
        self.unsubscribeHandlers = unsubscribeHandlers
        threadIDs = Set(channelsByThreadID.keys)
    }

    static func connect(
        client: PlatformClient,
        threads: [NetworkThread],
        organizationName: String?,
        onEvent: @escaping @Sendable (RoomChannelEvent) -> Void
    ) async throws -> RoomChannelSession {
        let socket = try await client.openSocket()
        do {
            var channels: [String: ApiChatChannel] = [:]
            var unsubscribeHandlers: [@Sendable () -> Void] = []

            let joined = try await withThrowingTaskGroup(
                of: (NetworkThread, ApiChatChannel).self
            ) { group in
                for thread in threads where !thread.id.isEmpty {
                    group.addTask {
                        let channel = try await ApiChatChannel.joinTeamThread(
                            socket: socket,
                            teamId: thread.networkID,
                            threadId: thread.id,
                            includeMetadata: true,
                            limit: TeamRoomAPI.messagePageSize
                        )
                        return (thread, channel)
                    }
                }
                var result: [(NetworkThread, ApiChatChannel)] = []
                for try await pair in group {
                    result.append(pair)
                }
                return result
            }

            for (thread, channel) in joined {
                channels[thread.id] = channel
                unsubscribeHandlers.append(
                    channel.onMessageAdded { payload in
                        onEvent(.messageAdded(networkID: thread.networkID, payload))
                    }
                )
                unsubscribeHandlers.append(
                    channel.onMessageUpdated { payload in
                        onEvent(.messageUpdated(networkID: thread.networkID, payload))
                    }
                )
                unsubscribeHandlers.append(
                    channel.onThreadEvent { payload in
                        onEvent(.threadEvent(networkID: thread.networkID, payload))
                    }
                )
                unsubscribeHandlers.append(
                    channel.onTyping { payload in
                        onEvent(.typing(payload))
                    }
                )
            }

            return RoomChannelSession(
                socket: socket,
                channelsByThreadID: channels,
                members: joined.flatMap { thread, channel in
                    TeamRoomAPI.mapChannelMembers(
                        joinResponse: channel.joinResponse,
                        networkID: thread.networkID,
                        organizationName: organizationName
                    )
                }.reduce(into: [NetworkMember]()) { result, member in
                    if !result.contains(where: { $0.id == member.id }) {
                        result.append(member)
                    }
                },
                unsubscribeHandlers: unsubscribeHandlers
            )
        } catch {
            await socket.disconnect()
            throw error
        }
    }

    func postMessage(
        threadID: String,
        content: String,
        idempotencyKey: String? = nil,
        uploads: [MessageUpload] = []
    ) async throws {
        guard let channel = channelsByThreadID[threadID], channel.channel.isJoined else {
            throw RoomChannelSessionError.unavailable(threadID)
        }
        let reply = try await channel.apiChatPostMessage(
            payload: ApiChatPostMessageInput(
                content: content,
                idempotencyKey: idempotencyKey ?? UUID().uuidString,
                uploads: uploads.isEmpty ? nil : uploads.map(\.channelPayload)
            )
        )
        try Self.requireSuccess(reply)
    }

    func deleteMessage(threadID: String, messageID: String) async throws {
        guard let channel = channelsByThreadID[threadID], channel.channel.isJoined else {
            throw RoomChannelSessionError.unavailable(threadID)
        }
        let reply = try await channel.apiChatDeleteMessage(
            payload: ApiChatDeleteMessageInput(messageId: messageID)
        )
        try Self.requireSuccess(reply)
    }

    func markRead(threadID: String, messageID: String) async throws {
        guard let channel = channelsByThreadID[threadID], channel.channel.isJoined else {
            throw RoomChannelSessionError.unavailable(threadID)
        }
        let reply = try await channel.apiChatMarkThreadRead(
            payload: ApiChatMarkThreadReadInput(messageId: messageID)
        )
        try Self.requireSuccess(reply)
    }

    func disconnect() async {
        for unsubscribe in unsubscribeHandlers {
            unsubscribe()
        }
        for channel in channelsByThreadID.values {
            try? await channel.leave()
        }
        await socket.disconnect()
    }

    private static func requireSuccess(_ reply: ChannelReply) throws {
        guard reply.status == "ok" else {
            let reason = reply.response["reason"]?.stringValue
                ?? reply.response["message"]?.stringValue
                ?? "The Team Room rejected the channel operation."
            throw RoomChannelSessionError.rejected(reason)
        }
    }
}
