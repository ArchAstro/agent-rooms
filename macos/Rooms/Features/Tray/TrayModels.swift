import SwiftUI

/// Mirrors the four sections in the ArchAgents network detail page.
enum TrayTab: String, CaseIterable, Identifiable {
    case connection = "Connection"
    case members = "Members"
    case chat = "Chat"
    case activity = "Activity"

    var id: String { rawValue }
}

struct NetworkSnapshot: Identifiable, Hashable {
    let id: String
    var name: String
    var relationship: String
    var unreadCount: Int
    var hostOrganization: String
    var collaboratorOrganization: String
    var slackChannel: String?

    static let empty = NetworkSnapshot(
        id: "",
        name: "Team Rooms",
        relationship: "",
        unreadCount: 0,
        hostOrganization: "",
        collaboratorOrganization: "",
        slackChannel: nil
    )
}

struct NetworkMember: Identifiable, Hashable {
    enum Kind: String { case agent = "Agent", user = "User" }
    enum Presence { case active, idle }

    let id: String
    var networkID: String
    var name: String
    var initials: String
    var kind: Kind
    var role: String
    var organization: String
    var joined: String
    var presence: Presence
}

struct NetworkThread: Identifiable, Hashable {
    let id: String
    var networkID: String
    var title: String
    var isDefault: Bool
    var unreadCount: Int

    static func empty(networkID: String) -> NetworkThread {
        NetworkThread(
            id: "",
            networkID: networkID,
            title: "Team Room",
            isDefault: true,
            unreadCount: 0
        )
    }
}

struct ChatMessage: Identifiable, Hashable {
    let id: String
    var threadID: String
    var author: String
    var initials: String
    var organization: String
    var body: String
    var time: String
    var isCurrentUser: Bool
    var attachmentName: String?
}

struct ThreadTask: Identifiable, Hashable {
    enum State: String { case running = "Running", completed = "Completed", blocked = "Blocked" }
    let id: String
    var threadID: String
    var title: String
    var assignee: String
    var state: State
}

struct WorkstreamItem: Identifiable, Hashable {
    enum Kind: String { case routine = "Routine", thread = "Thread" }
    let id: String
    var networkID: String
    var kind: Kind
    var title: String
    var detail: String
    var time: String
}

/// Network-scoped activity, using the same levels as the web activity feed.
/// It also drives the optional native overlay.
struct StreamEvent: Identifiable, Hashable {
    enum Level: String, CaseIterable, Identifiable {
        case all = "All"
        case debug = "Debug"
        case info = "Info"
        case warning = "Warn"
        case error = "Error"
        case audit = "Audit"

        var id: String { rawValue }
        var systemImage: String {
            switch self {
            case .all, .info: "info.circle.fill"
            case .debug: "ladybug.fill"
            case .warning: "exclamationmark.triangle.fill"
            case .error: "xmark.octagon.fill"
            case .audit: "checkmark.shield.fill"
            }
        }
        var color: Color {
            switch self {
            case .all, .info: Theme.blue
            case .debug: Theme.muted2
            case .warning: Theme.amber
            case .error: Theme.red
            case .audit: Theme.green
            }
        }
        var background: Color {
            switch self {
            case .all, .info: Theme.blue.opacity(0.10)
            case .debug: Theme.surface
            case .warning: Theme.amberSoft
            case .error: Theme.redSoft
            case .audit: Theme.greenSoft
            }
        }
    }

    let id: String
    var networkID: String
    var level: Level
    var author: String
    var body: String
    var time: String
    var sessionID: String

    func matches(_ filter: Level) -> Bool { filter == .all || level == filter }
}

enum TrayPlaceholders {
    static let networks = [
        NetworkSnapshot(
            id: "net_archastro",
            name: "ArchAstro Team",
            relationship: "ArchAstro ↔ Launch Partners",
            unreadCount: 3,
            hostOrganization: "ArchAstro",
            collaboratorOrganization: "Launch Partners",
            slackChannel: "#customer-archastro"
        ),
        NetworkSnapshot(
            id: "net_design",
            name: "Design Partners",
            relationship: "ArchAstro ↔ Design Partners",
            unreadCount: 0,
            hostOrganization: "ArchAstro",
            collaboratorOrganization: "Design Partners",
            slackChannel: nil
        ),
    ]

    static let members = [
        NetworkMember(id: "calvin", networkID: "net_archastro", name: "Calvin", initials: "CG", kind: .user, role: "Owner", organization: "ArchAstro", joined: "Jul 12", presence: .active),
        NetworkMember(id: "bruno", networkID: "net_archastro", name: "Bruno", initials: "B", kind: .agent, role: "Member", organization: "ArchAstro", joined: "Jul 14", presence: .active),
        NetworkMember(id: "launch", networkID: "net_archastro", name: "Launch Operator", initials: "LO", kind: .user, role: "Member", organization: "Launch Partners", joined: "Jul 19", presence: .idle),
        NetworkMember(id: "fleet", networkID: "net_archastro", name: "Fleet", initials: "F", kind: .agent, role: "Member", organization: "Launch Partners", joined: "Jul 19", presence: .active),
        NetworkMember(id: "design", networkID: "net_design", name: "Design Partner", initials: "DP", kind: .user, role: "Member", organization: "Design Partners", joined: "Jul 25", presence: .active),
        NetworkMember(id: "muse", networkID: "net_design", name: "Muse", initials: "M", kind: .agent, role: "Member", organization: "ArchAstro", joined: "Jul 25", presence: .active),
    ]

    static let threads = [
        NetworkThread(id: "thread_general", networkID: "net_archastro", title: "General", isDefault: true, unreadCount: 2),
        NetworkThread(id: "thread_launch", networkID: "net_archastro", title: "Launch readiness", isDefault: false, unreadCount: 1),
        NetworkThread(id: "thread_feedback", networkID: "net_archastro", title: "Product feedback", isDefault: false, unreadCount: 0),
        NetworkThread(id: "thread_design", networkID: "net_design", title: "Design review", isDefault: true, unreadCount: 0),
    ]

    static let messages = [
        ChatMessage(id: "m1", threadID: "thread_general", author: "Launch Operator", initials: "LO", organization: "Launch Partners", body: "The release candidate is ready for the final customer-path check.", time: "10:24", isCurrentUser: false, attachmentName: "release-checklist.pdf"),
        ChatMessage(id: "m2", threadID: "thread_general", author: "Bruno", initials: "B", organization: "ArchAstro", body: "I ran the workflow against the production-shaped fixture. All tasks completed and the audit entries look right.", time: "10:27", isCurrentUser: false, attachmentName: nil),
        ChatMessage(id: "m3", threadID: "thread_general", author: "You", initials: "CG", organization: "ArchAstro", body: "Great. I’ll keep the thread open while we verify the Slack handoff.", time: "10:31", isCurrentUser: true, attachmentName: nil),
        ChatMessage(id: "m4", threadID: "thread_design", author: "Design Partner", initials: "DP", organization: "Design Partners", body: "The updated navigation hierarchy is ready for review.", time: "11:06", isCurrentUser: false, attachmentName: nil),
    ]

    static let tasks = [
        ThreadTask(id: "task1", threadID: "thread_general", title: "Verify customer path", assignee: "Bruno", state: .completed),
        ThreadTask(id: "task2", threadID: "thread_general", title: "Confirm Slack handoff", assignee: "Calvin", state: .running),
        ThreadTask(id: "task3", threadID: "thread_design", title: "Review navigation hierarchy", assignee: "Muse", state: .running),
    ]

    static let workstream = [
        WorkstreamItem(id: "w1", networkID: "net_archastro", kind: .thread, title: "Launch readiness", detail: "3 new messages", time: "now"),
        WorkstreamItem(id: "w2", networkID: "net_archastro", kind: .routine, title: "Customer health check", detail: "Completed successfully", time: "18m"),
        WorkstreamItem(id: "w3", networkID: "net_archastro", kind: .thread, title: "Product feedback", detail: "Fleet added a response", time: "42m"),
        WorkstreamItem(id: "w4", networkID: "net_design", kind: .thread, title: "Design review", detail: "1 new message", time: "now"),
    ]

    static let events = [
        StreamEvent(id: "a1", networkID: "net_archastro", level: .audit, author: "Bruno", body: "Completed task “Verify customer path”.", time: "now", sessionID: "ses_8a21"),
        StreamEvent(id: "a2", networkID: "net_archastro", level: .info, author: "Fleet", body: "Posted a response in Launch readiness.", time: "8m", sessionID: "ses_7f02"),
        StreamEvent(id: "a3", networkID: "net_archastro", level: .warning, author: "Slack", body: "Channel delivery retried after a transient timeout.", time: "26m", sessionID: "ses_70cd"),
        StreamEvent(id: "a4", networkID: "net_archastro", level: .audit, author: "Calvin", body: "Updated the collaborator connection.", time: "1h", sessionID: "ses_622f"),
        StreamEvent(id: "a5", networkID: "net_design", level: .info, author: "Muse", body: "Opened the Design review thread.", time: "4m", sessionID: "ses_design"),
    ]

    static let liveFeed = [
        StreamEvent(id: "live1", networkID: "net_archastro", level: .info, author: "Fleet", body: "Posted a new message in Launch readiness.", time: "now", sessionID: "ses_live1"),
        StreamEvent(id: "live2", networkID: "net_archastro", level: .audit, author: "Bruno", body: "Completed a thread task.", time: "now", sessionID: "ses_live2"),
    ]
}
