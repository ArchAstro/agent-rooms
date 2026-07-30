import SwiftUI
import ArchAstroPlatform

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
    var agentMode: String?
    var attachments: [ChatAttachment]

    var roomPost: RoomPostPresentation? {
        RoomPostPresentation.parse(body)
    }

    var displayAuthor: String {
        roomPost?.author ?? author
    }

    var displayInitials: String {
        roomPost.map { TeamRoomAPI.initials(for: $0.author) } ?? initials
    }

    var displayBody: String {
        roomPost?.body ?? body
    }
}

enum RoomPostKind: String, Hashable {
    case done = "✓"
    case start = "▶"
    case lesson = "⚠"
    case handoff = "→"
    case abandoned = "✗"
    case question = "?"

    var label: String {
        switch self {
        case .done: "Done"
        case .start: "Start"
        case .lesson: "Lesson"
        case .handoff: "Handoff"
        case .abandoned: "Abandoned"
        case .question: "Question"
        }
    }

    var color: Color {
        switch self {
        case .done: Theme.green
        case .start: Theme.blue
        case .lesson: Theme.amber
        case .handoff: Color.cyan
        case .abandoned: Theme.muted2
        case .question: Color.purple
        }
    }
}

struct RoomPostPresentation: Hashable {
    var kind: RoomPostKind
    var author: String
    var tag: String
    var body: String

    static func parse(_ content: String) -> RoomPostPresentation? {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let glyph = trimmed.first,
              let kind = RoomPostKind(rawValue: String(glyph))
        else { return nil }

        let afterGlyph = trimmed.dropFirst()
            .trimmingCharacters(in: .whitespaces)
        let pattern = #"^([A-Za-z][\w .'-]{0,24})\s*\(([\w-]{1,40})\):\s*"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(
                in: afterGlyph,
                range: NSRange(afterGlyph.startIndex..., in: afterGlyph)
              ),
              let authorRange = Range(match.range(at: 1), in: afterGlyph),
              let tagRange = Range(match.range(at: 2), in: afterGlyph),
              let prefixRange = Range(match.range(at: 0), in: afterGlyph)
        else { return nil }

        var body = String(afterGlyph[prefixRange.upperBound...])
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let duplicate = body.first,
           "✓▶⚠→✗?🔔".contains(duplicate)
        {
            body = String(body.dropFirst())
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return RoomPostPresentation(
            kind: kind,
            author: String(afterGlyph[authorRange])
                .trimmingCharacters(in: .whitespaces),
            tag: String(afterGlyph[tagRange])
                .trimmingCharacters(in: .whitespaces),
            body: body
        )
    }
}

struct ChatAttachment: Identifiable, Hashable {
    let id: String
    var type: String
    var filename: String?
    var contentType: String?
    var url: String?
    var title: String?
    var description: String?
    var imageURL: String?
    var imageSourceURL: String?
    var width: Int?
    var height: Int?
    var version: Int?
    var name: String?
    var mediaType: String?
    var status: String?
    var object: JSONValue?

    init(
        id: String,
        type: String,
        filename: String? = nil,
        contentType: String? = nil,
        url: String? = nil,
        title: String? = nil,
        description: String? = nil,
        imageURL: String? = nil,
        imageSourceURL: String? = nil,
        width: Int? = nil,
        height: Int? = nil,
        version: Int? = nil,
        name: String? = nil,
        mediaType: String? = nil,
        status: String? = nil,
        object: JSONValue? = nil
    ) {
        self.id = id
        self.type = type
        self.filename = filename
        self.contentType = contentType
        self.url = url
        self.title = title
        self.description = description
        self.imageURL = imageURL
        self.imageSourceURL = imageSourceURL
        self.width = width
        self.height = height
        self.version = version
        self.name = name
        self.mediaType = mediaType
        self.status = status
        self.object = object
    }

    var displayName: String {
        filename ?? title ?? name ?? type.replacingOccurrences(of: "_", with: " ").capitalized
    }

    var resolvedURL: URL? {
        [url, imageURL, imageSourceURL]
            .compactMap { $0.flatMap(URL.init(string:)) }
            .filter { ["http", "https"].contains($0.scheme?.lowercased() ?? "") }
            .first
    }

    var isImage: Bool {
        type == "image"
            || contentType?.hasPrefix("image/") == true
            || imageSourceURL != nil
    }

    var chart: ChatChart? {
        guard type == "chart", let object else { return nil }
        return ChatChart(object: object)
    }

    var task: ChatTaskAttachment? {
        guard type == "task" else { return nil }
        return ChatTaskAttachment(attachment: self)
    }
}

struct ChatTaskAttachment: Hashable {
    var name: String
    var description: String?
    var status: String?
    var ownerName: String?
    var ownerImageURL: String?
    var dueDate: String?
    var subtasksCount: Int

    init(attachment: ChatAttachment) {
        let object = attachment.object
        name = attachment.title
            ?? object?["name"]?.stringValue
            ?? "Task"
        description = attachment.description
            ?? object?["description"]?.stringValue
        status = attachment.status
            ?? object?["status"]?.stringValue
        let owner = object?["owner_actor"]
        ownerName = owner?["name"]?.stringValue
            ?? owner?["alias"]?.stringValue
        ownerImageURL = owner?["profile_picture"]?["url"]?.stringValue
        dueDate = object?["due_date"]?.stringValue
        subtasksCount = object?["subtasks_count"]?.intValue ?? 0
    }
}

enum ChatChart: Hashable {
    enum SeriesKind: String, Hashable {
        case bars, line, area, composed
    }

    enum CellKind: String, Hashable {
        case treemap, pie
    }

    struct Series: Hashable, Identifiable {
        var id: String
        var name: String
        var values: [Double]
        var presentation: String?
        var axis: String?
    }

    struct Cell: Hashable, Identifiable {
        var id: String
        var name: String
        var size: Double
        var heat: Double?
    }

    struct Point: Hashable, Identifiable {
        var id: String
        var x: Double
        var y: Double
    }

    struct PointGroup: Hashable, Identifiable {
        var id: String
        var name: String
        var points: [Point]
    }

    case series(
        kind: SeriesKind,
        title: String?,
        unit: String?,
        categories: [String],
        series: [Series]
    )
    case cells(kind: CellKind, title: String?, cells: [Cell])
    case scatter(
        title: String?,
        xLabel: String?,
        yLabel: String?,
        groups: [PointGroup]
    )

    init?(object: JSONValue) {
        guard let spec = object["spec"],
              let kind = spec["kind"]?.stringValue
        else { return nil }
        let title = spec["title"]?.stringValue ?? object["title"]?.stringValue

        if let seriesKind = SeriesKind(rawValue: kind),
           let categories = Self.stringArray(spec["categories"]),
           !categories.isEmpty,
           let series = Self.seriesArray(spec["series"]),
           !series.isEmpty
        {
            self = .series(
                kind: seriesKind,
                title: title,
                unit: spec["unit"]?.stringValue,
                categories: categories,
                series: series
            )
            return
        }

        if let cellKind = CellKind(rawValue: kind),
           let cells = Self.cellArray(spec["cells"]),
           !cells.isEmpty
        {
            self = .cells(kind: cellKind, title: title, cells: cells)
            return
        }

        guard kind == "scatter",
              let groups = Self.pointGroups(spec["groups"]),
              !groups.isEmpty
        else { return nil }
        self = .scatter(
            title: title,
            xLabel: spec["xLabel"]?.stringValue,
            yLabel: spec["yLabel"]?.stringValue,
            groups: groups
        )
    }

    private static func stringArray(_ value: JSONValue?) -> [String]? {
        guard let raw = value?.arrayValue else { return nil }
        var result: [String] = []
        for value in raw {
            guard let string = value.stringValue else { return nil }
            result.append(string)
        }
        return result
    }

    private static func finiteDoubleArray(_ value: JSONValue?) -> [Double]? {
        guard let raw = value?.arrayValue else { return nil }
        var result: [Double] = []
        for value in raw {
            guard let number = value.doubleValue, number.isFinite else { return nil }
            result.append(number)
        }
        return result
    }

    private static func seriesArray(_ value: JSONValue?) -> [Series]? {
        guard let raw = value?.arrayValue else { return nil }
        var result: [Series] = []
        for (index, value) in raw.enumerated() {
            guard let name = value["name"]?.stringValue,
                  let values = finiteDoubleArray(value["values"]),
                  !values.isEmpty
            else { return nil }
            result.append(
                Series(
                    id: "series-\(index)",
                    name: name,
                    values: values,
                    presentation: value["as"]?.stringValue,
                    axis: value["axis"]?.stringValue
                )
            )
        }
        return result
    }

    private static func cellArray(_ value: JSONValue?) -> [Cell]? {
        guard let raw = value?.arrayValue else { return nil }
        var result: [Cell] = []
        for (index, value) in raw.enumerated() {
            guard let name = value["name"]?.stringValue,
                  let size = value["size"]?.doubleValue,
                  size.isFinite
            else { return nil }
            let heat = value["heat"]?.doubleValue
            if let heat, !heat.isFinite { return nil }
            result.append(
                Cell(
                    id: "cell-\(index)",
                    name: name,
                    size: size,
                    heat: heat
                )
            )
        }
        return result
    }

    private static func pointGroups(_ value: JSONValue?) -> [PointGroup]? {
        guard let raw = value?.arrayValue else { return nil }
        var result: [PointGroup] = []
        for (groupIndex, value) in raw.enumerated() {
            guard let name = value["name"]?.stringValue,
                  let rawPoints = value["points"]?.arrayValue,
                  !rawPoints.isEmpty
            else { return nil }
            var points: [Point] = []
            for (pointIndex, point) in rawPoints.enumerated() {
                guard let x = point["x"]?.doubleValue,
                      let y = point["y"]?.doubleValue,
                      x.isFinite,
                      y.isFinite
                else { return nil }
                points.append(
                    Point(
                        id: "point-\(groupIndex)-\(pointIndex)",
                        x: x,
                        y: y
                    )
                )
            }
            result.append(
                PointGroup(
                    id: "group-\(groupIndex)",
                    name: name,
                    points: points
                )
            )
        }
        return result
    }
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
        ChatMessage(
            id: "m1",
            threadID: "thread_general",
            author: "Launch Operator",
            initials: "LO",
            organization: "Launch Partners",
            body: "The release candidate is ready for the final customer-path check.",
            time: "10:24",
            isCurrentUser: false,
            agentMode: nil,
            attachments: [
                ChatAttachment(
                    id: "file1",
                    type: "file",
                    filename: "release-checklist.pdf",
                    contentType: "application/pdf"
                )
            ]
        ),
        ChatMessage(id: "m2", threadID: "thread_general", author: "Bruno", initials: "B", organization: "ArchAstro", body: "I ran the workflow against the production-shaped fixture. All tasks completed and the audit entries look right.", time: "10:27", isCurrentUser: false, agentMode: nil, attachments: []),
        ChatMessage(id: "m3", threadID: "thread_general", author: "You", initials: "CG", organization: "ArchAstro", body: "Great. I’ll keep the thread open while we verify the Slack handoff.", time: "10:31", isCurrentUser: true, agentMode: nil, attachments: []),
        ChatMessage(id: "m4", threadID: "thread_design", author: "Design Partner", initials: "DP", organization: "Design Partners", body: "The updated navigation hierarchy is ready for review.", time: "11:06", isCurrentUser: false, agentMode: nil, attachments: []),
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
