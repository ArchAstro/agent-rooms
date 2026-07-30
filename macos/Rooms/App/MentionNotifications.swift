import Foundation
import UserNotifications

struct MentionIdentity: Equatable, Sendable {
    var fullName: String?
    var alias: String?
    var email: String?

    fileprivate var nameTerms: Set<String> {
        let parts = (fullName ?? "")
            .split(whereSeparator: \.isWhitespace)
            .map(String.init)
        var terms: Set<String> = []
        if let first = parts.first { terms.insert(first) }
        if let last = parts.last { terms.insert(last) }
        if parts.count > 1 { terms.insert(parts.joined(separator: " ")) }
        return Set(terms.map(Self.fold).filter { !$0.isEmpty })
    }

    fileprivate var handles: Set<String> {
        let nameParts = (fullName ?? "")
            .split(whereSeparator: \.isWhitespace)
            .map(String.init)
        var candidates: [String] = []
        if let alias {
            candidates.append(alias.trimmingCharacters(in: CharacterSet(charactersIn: "@")))
        }
        if let localPart = email?.split(separator: "@", maxSplits: 1).first {
            candidates.append(String(localPart).split(separator: "+", maxSplits: 1).first.map(String.init) ?? "")
        }
        if let first = nameParts.first { candidates.append(first) }
        if let last = nameParts.last { candidates.append(last) }
        if nameParts.count > 1 {
            candidates.append(nameParts.joined())
            candidates.append(nameParts.joined(separator: "."))
            candidates.append(nameParts.joined(separator: "_"))
        }
        return Set(candidates.map(Self.fold).filter { !$0.isEmpty })
    }

    fileprivate static func fold(_ value: String) -> String {
        value
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
            .lowercased()
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

enum MentionMatcher {
    static func matches(_ text: String, identity: MentionIdentity) -> Bool {
        let foldedText = MentionIdentity.fold(text)
        guard !foldedText.isEmpty else { return false }

        let handles = identity.handles
        guard let tagRegex = try? NSRegularExpression(
            pattern: #"(?<![\p{L}\p{N}_])@([\p{L}\p{N}_][\p{L}\p{N}_.-]*)"#
        ) else {
            return identity.nameTerms.contains(where: {
                containsDelimitedName($0, in: foldedText)
            })
        }
        let range = NSRange(foldedText.startIndex..., in: foldedText)
        let tagMatches = tagRegex.matches(in: foldedText, range: range)
        if tagMatches.contains(where: { match in
            guard let handleRange = Range(match.range(at: 1), in: foldedText) else {
                return false
            }
            return handles.contains(String(foldedText[handleRange]))
        }) {
            return true
        }

        // A different @tag must not become a plain-name match. For example,
        // @calvin-g-extra should not match the first name "Calvin".
        let atTokenRegex = try? NSRegularExpression(
            pattern: #"@[\p{L}\p{N}_][\p{L}\p{N}_.-]*"#
        )
        let textWithoutTags = atTokenRegex?.stringByReplacingMatches(
            in: foldedText,
            range: range,
            withTemplate: " "
        ) ?? foldedText
        return identity.nameTerms.contains(where: {
            containsDelimitedName($0, in: textWithoutTags)
        })
    }

    private static func containsDelimitedName(_ name: String, in text: String) -> Bool {
        let words = name
            .split(whereSeparator: \.isWhitespace)
            .map { NSRegularExpression.escapedPattern(for: String($0)) }
        guard !words.isEmpty else { return false }
        let phrase = words.joined(separator: #"\s+"#)
        let pattern = #"(?<![\p{L}\p{N}_])"# + phrase + #"(?![\p{L}\p{N}_])"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return false
        }
        return regex.firstMatch(
            in: text,
            range: NSRange(text.startIndex..., in: text)
        ) != nil
    }
}

struct MentionNavigationTarget: Equatable, Sendable {
    var networkID: String
    var threadID: String
    var messageID: String
}

struct MessageFocus: Equatable, Sendable {
    var threadID: String
    var messageID: String
    var requestID = UUID()
}

struct MessageMention: Equatable, Sendable {
    static let categoryIdentifier = "ROOMS_MESSAGE_MENTION"

    private enum Key {
        static let networkID = "network_id"
        static let threadID = "thread_id"
        static let messageID = "message_id"
        static let roomName = "room_name"
        static let threadName = "thread_name"
        static let author = "author"
        static let body = "body"
    }

    var target: MentionNavigationTarget
    var roomName: String
    var threadName: String
    var author: String
    var body: String

    var requestIdentifier: String {
        "rooms.mention.\(target.messageID)"
    }

    var userInfo: [AnyHashable: Any] {
        [
            Key.networkID: target.networkID,
            Key.threadID: target.threadID,
            Key.messageID: target.messageID,
            Key.roomName: roomName,
            Key.threadName: threadName,
            Key.author: author,
            Key.body: body,
        ]
    }

    init(
        target: MentionNavigationTarget,
        roomName: String,
        threadName: String,
        author: String,
        body: String
    ) {
        self.target = target
        self.roomName = roomName
        self.threadName = threadName
        self.author = author
        self.body = body
    }

    init?(userInfo: [AnyHashable: Any]) {
        guard let networkID = userInfo[Key.networkID] as? String,
              let threadID = userInfo[Key.threadID] as? String,
              let messageID = userInfo[Key.messageID] as? String,
              let roomName = userInfo[Key.roomName] as? String,
              let threadName = userInfo[Key.threadName] as? String,
              let author = userInfo[Key.author] as? String,
              let body = userInfo[Key.body] as? String
        else { return nil }
        self.init(
            target: MentionNavigationTarget(
                networkID: networkID,
                threadID: threadID,
                messageID: messageID
            ),
            roomName: roomName,
            threadName: threadName,
            author: author,
            body: body
        )
    }

    func content() -> UNMutableNotificationContent {
        let content = UNMutableNotificationContent()
        content.title = "\(author) mentioned you"
        content.subtitle = "\(roomName) · \(threadName)"
        content.body = body
        content.sound = .default
        content.categoryIdentifier = Self.categoryIdentifier
        content.threadIdentifier = target.threadID
        content.userInfo = userInfo
        return content
    }
}

@MainActor
final class MentionNotifier {
    private let center: UNUserNotificationCenter

    init(center: UNUserNotificationCenter = .current()) {
        self.center = center
    }

    func configure(delegate: any UNUserNotificationCenterDelegate) {
        center.delegate = delegate
        center.setNotificationCategories([
            UNNotificationCategory(
                identifier: MessageMention.categoryIdentifier,
                actions: [],
                intentIdentifiers: [],
                options: []
            )
        ])
        Task {
            _ = try? await center.requestAuthorization(options: [.alert, .sound])
        }
    }

    func deliver(_ mention: MessageMention) {
        let request = UNNotificationRequest(
            identifier: mention.requestIdentifier,
            content: mention.content(),
            trigger: nil
        )
        Task {
            try? await center.add(request)
        }
    }
}
