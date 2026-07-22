import Foundation

/// A room in the sidebar. Placeholder shape until rooms are backed by the
/// platform's thread APIs (`client.threads` / `ApiChatChannel`).
struct Room: Identifiable, Hashable {
    let id: String
    var name: String
    var unreadCount: Int = 0

    static let placeholders: [Room] = [
        Room(id: "general", name: "General"),
        Room(id: "support", name: "Support", unreadCount: 3),
        Room(id: "agents", name: "Agents"),
    ]
}
