import SwiftUI

/// Placeholder content mirroring the menu-bar mock. These shapes are what
/// the room stream, inbox, and picture will hydrate from the platform
/// (threads + ApiChatChannel) in the next milestone.

enum TrayTab: String, CaseIterable, Identifiable {
    case picture = "Picture"
    case inbox = "Inbox"
    case stream = "Stream"

    var id: String { rawValue }
}

struct RoomSnapshot: Identifiable, Hashable {
    let id: String
    var name: String
    var meta: String
    var unreadCount: Int
    var greeting: String
    var stats: String
    var digestTitle: String
    var digestText: String
    var digestCaution: String
}

struct SummaryPerson: Identifiable, Hashable {
    let id: String
    var initials: String
    var name: String
    var work: String
    var status: String
    var statusKind: StatusKind
    var avatarColor: Color

    enum StatusKind {
        case go, done, wait

        var color: Color {
            switch self {
            case .go: Theme.purple
            case .done: Theme.green
            case .wait: Theme.amber
            }
        }

        var background: Color {
            switch self {
            case .go: Theme.purpleSoft
            case .done: Theme.greenSoft
            case .wait: Theme.amberSoft
            }
        }
    }
}

struct DecisionCard: Identifiable, Hashable {
    let id: String
    var title: String
    var body: String
    var provenance: String
    var time: String
}

struct InboxRequest: Identifiable, Hashable {
    enum Kind {
        case approval, handoff, notice

        var label: String {
            switch self {
            case .approval: "Approval"
            case .handoff: "Handoff"
            case .notice: "For you"
            }
        }

        var color: Color {
            switch self {
            case .approval: Theme.amber
            case .handoff: Theme.purple
            case .notice: Theme.blue
            }
        }
    }

    let id: String
    var kind: Kind
    var source: String
    var time: String
    var title: String
    var body: String
    var primaryAction: String
    var secondaryAction: String
}

struct StreamEvent: Identifiable, Hashable {
    enum Kind {
        case done, start, lesson

        var glyph: String {
            switch self {
            case .done: "✓"
            case .start: "▶"
            case .lesson: "!"
            }
        }

        var color: Color {
            switch self {
            case .done: Theme.green
            case .start: Theme.purple
            case .lesson: Theme.amber
            }
        }

        var background: Color {
            switch self {
            case .done: Theme.greenSoft
            case .start: Theme.purpleSoft
            case .lesson: Theme.amberSoft
            }
        }
    }

    enum Filter: String, CaseIterable, Identifiable {
        case all = "All"
        case you = "You"
        case lessons = "Lessons"

        var id: String { rawValue }
    }

    let id: String
    var kind: Kind
    var author: String
    var body: String
    var time: String
    var isYou: Bool

    func matches(_ filter: Filter) -> Bool {
        switch filter {
        case .all: true
        case .you: isYou
        case .lessons: kind == .lesson
        }
    }
}

// MARK: - Placeholder content (mock parity)

enum TrayPlaceholders {
    static let rooms: [RoomSnapshot] = [
        RoomSnapshot(
            id: "team",
            name: "ArchAstro Team Room",
            meta: "6 people · 18 sessions",
            unreadCount: 3,
            greeting: "Good afternoon, Calvin.",
            stats: "18 active sessions · 7 things landed",
            digestTitle: "Seven landed. Two still moving. One deserves a look.",
            digestText: "Zoom OAuth is up for review with live authorization verified. Code Search is moving through the full production deployment. Task dependencies and multi-org networks landed today.",
            digestCaution: "The only caution: generic webhook identity still doesn't close the delivery-suppression root cause."
        ),
        RoomSnapshot(
            id: "deployments",
            name: "Deployments",
            meta: "CI and release watches",
            unreadCount: 0,
            greeting: "Two releases are moving.",
            stats: "4 active watches · latest check 2m ago",
            digestTitle: "Code Search is converging on a busy main.",
            digestText: "PR 8141 is through review and moving across main CI, image publication, release validation, and guarded infrastructure apply.",
            digestCaution: "The release stays pinned to frozen tested source and an immutable reviewed digest."
        ),
        RoomSnapshot(
            id: "customer-watch",
            name: "Customer watch",
            meta: "shared support signal",
            unreadCount: 1,
            greeting: "Customer watch is quiet.",
            stats: "2 standing watches · 0 urgent",
            digestTitle: "No new customer-critical signal.",
            digestText: "The Slack friction audit reclassified several reported issues, and the live-session attach bug is already fixed and verified.",
            digestCaution: "One webhook identity concern remains a correctness issue, not a customer outage."
        ),
    ]

    static let people: [SummaryPerson] = [
        SummaryPerson(
            id: "vivek", initials: "VK", name: "Vivek",
            work: "magic-link callback stack · CI running",
            status: "watching", statusKind: .wait, avatarColor: Color(hex: 0x6557C7)
        ),
        SummaryPerson(
            id: "calvin", initials: "CG", name: "Calvin",
            work: "Code Search production deployment",
            status: "in flight", statusKind: .go, avatarColor: Color(hex: 0x58544E)
        ),
        SummaryPerson(
            id: "bruno", initials: "B", name: "Bruno",
            work: "N-org networks and task dependencies",
            status: "landed", statusKind: .done, avatarColor: Color(hex: 0xA26537)
        ),
        SummaryPerson(
            id: "rob", initials: "RM", name: "Rob",
            work: "failed-provision cleanup ledger",
            status: "local", statusKind: .go, avatarColor: Color(hex: 0x397A6C)
        ),
    ]

    static let decision = DecisionCard(
        id: "webhook-identity",
        title: "Webhook identity change should not merge as written",
        body: "Correlation headers are still treated as trusted idempotency contracts, and receipt retention can disagree with permanent downstream uniqueness.",
        provenance: "Arne · review of PR 8032",
        time: "1h ago"
    )

    static let requests: [InboxRequest] = [
        InboxRequest(
            id: "code-search-release",
            kind: .approval,
            source: "Calvin · Code Search",
            time: "2m",
            title: "Release PR is green and main moved. Continue with the rebased, revalidated release?",
            body: "Production still deploys the frozen tested source plus the reviewed immutable digest.",
            primaryAction: "Approve",
            secondaryAction: "Hold"
        ),
        InboxRequest(
            id: "tray-handoff",
            kind: .handoff,
            source: "Rob · Team Room roadmap",
            time: "18m",
            title: "Take the tray prototype into the next Team Room product review?",
            body: "The roadmap now makes the room the center and Slack channels a recorder-to-summary input.",
            primaryAction: "Accept",
            secondaryAction: "Not now"
        ),
        InboxRequest(
            id: "webhook-notice",
            kind: .notice,
            source: "Arne · Webhooks",
            time: "1h",
            title: "PR 8032 still misses the root cause; retention and permanent uniqueness can disagree.",
            body: "Read-only review is complete. No customer action is required.",
            primaryAction: "Mark seen",
            secondaryAction: "Open PR"
        ),
    ]

    /// Rotating queue for the simulated live feed.
    static let liveFeed: [StreamEvent] = [
        StreamEvent(
            id: "live1", kind: .start, author: "Fleet · librarian",
            body: "Distilling the last hour of session exhaust into the digest.",
            time: "now", isYou: false
        ),
        StreamEvent(
            id: "live2", kind: .done, author: "CI · code-search",
            body: "Release validation finished green across the full matrix.",
            time: "now", isYou: false
        ),
        StreamEvent(
            id: "live3", kind: .lesson, author: "Team record",
            body: "Prism dynamic mocks hide missing-field bugs; contract tests decode strictly on purpose.",
            time: "now", isYou: false
        ),
        StreamEvent(
            id: "live4", kind: .start, author: "You · rooms",
            body: "Aligning the native tray to the menu-bar mock.",
            time: "now", isYou: true
        ),
    ]

    static let events: [StreamEvent] = [
        StreamEvent(
            id: "e1", kind: .done, author: "Calvin · wt3",
            body: "Zoom OAuth is pushed as PR 8143; provider remains hidden from public surfaces.",
            time: "2m", isYou: false
        ),
        StreamEvent(
            id: "e2", kind: .start, author: "You · wt7",
            body: "Designing a macOS-native Team Room tray mock.",
            time: "4m", isYou: true
        ),
        StreamEvent(
            id: "e3", kind: .start, author: "Calvin · wte",
            body: "Watching Code Search through a complete production deployment.",
            time: "5m", isYou: false
        ),
        StreamEvent(
            id: "e4", kind: .done, author: "Bruno · multi-org-networks",
            body: "Networks now accept three or more collaborating orgs.",
            time: "21m", isYou: false
        ),
        StreamEvent(
            id: "e5", kind: .done, author: "Rob · wt7",
            body: "Failed-provision cleanup ledger is implemented locally and focused tests pass.",
            time: "24m", isYou: false
        ),
        StreamEvent(
            id: "e6", kind: .lesson, author: "Arne · webhook review",
            body: "Generic correlation headers are still trusted by default; the current patch should not merge.",
            time: "1h", isYou: false
        ),
        StreamEvent(
            id: "e7", kind: .done, author: "Vivek · wt6",
            body: "The corrected seven-PR magic-link callback stack is published and CI is running.",
            time: "20h", isYou: false
        ),
        StreamEvent(
            id: "e8", kind: .lesson, author: "Team record",
            body: "Talk to vks in plain English. The room keeps this as a craft rule.",
            time: "2d", isYou: false
        ),
    ]
}
