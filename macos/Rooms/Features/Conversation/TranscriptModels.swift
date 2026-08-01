import Foundation

struct ConversationTarget: Equatable, Sendable {
    var networkName: String
    var threadName: String
    var threadID: String
}

struct RecordedConversationAudio: Equatable, Sendable {
    var fileURL: URL
    var duration: TimeInterval
    var recordedAt: Date
}

struct ConversationTranscriptSegment: Identifiable, Equatable, Sendable {
    var id: String
    var speakerID: String
    var startTime: TimeInterval
    var endTime: TimeInterval
    var text: String
}

struct LocalConversationTranscript: Equatable, Sendable {
    var segments: [ConversationTranscriptSegment]
    var usedSpeakerDiarization: Bool
    var speakerSeparationFallback: SpeakerSeparationFallbackReason? = nil
}

enum SpeakerSeparationFallbackReason: Equatable, Sendable {
    case wordTimingsUnavailable
    case insufficientSpeech
    case modelUnavailable
    case processingFailed

    var reviewMessage: String {
        switch self {
        case .wordTimingsUnavailable:
            "Word timings were unavailable, so speakers could not be matched to the transcript. Add speakers and assign rows manually."
        case .insufficientSpeech:
            "There was not enough continuous speech to identify speakers. Add speakers and assign rows manually."
        case .modelUnavailable:
            "The local speaker model could not be prepared. Add speakers and assign rows manually."
        case .processingFailed:
            "Speaker separation could not process this recording. Add speakers and assign rows manually."
        }
    }
}

struct ConversationTranscriptDraft: Equatable, Sendable {
    var recordedAt: Date
    var duration: TimeInterval
    var target: ConversationTarget
    var segments: [ConversationTranscriptSegment]
    var speakerNames: [String: String]
    var usedSpeakerDiarization: Bool
    var speakerSeparationFallback: SpeakerSeparationFallbackReason? = nil

    var orderedSpeakerIDs: [String] {
        var seen: Set<String> = []
        return segments.compactMap { segment in
            seen.insert(segment.speakerID).inserted ? segment.speakerID : nil
        } + speakerNames.keys.sorted().filter { !seen.contains($0) }
    }
}

struct LocalModelPreparation: Equatable, Sendable {
    var modelName: String
    var fractionCompleted: Double?
    var detail: String

    static let speechStarting = LocalModelPreparation(
        modelName: "speech recognition model",
        fractionCompleted: nil,
        detail: "Checking the local model cache. First use downloads about 500 MB."
    )

    static let speakerStarting = LocalModelPreparation(
        modelName: "speaker separation model",
        fractionCompleted: nil,
        detail: "Preparing the local speaker model. Audio stays on this Mac."
    )
}

enum LocalTranscriptionStage: Equatable, Sendable {
    case preparingModel(LocalModelPreparation)
    case transcribing
    case separatingSpeakers
    case buildingTranscript

    var label: String {
        switch self {
        case .preparingModel(let preparation):
            "Preparing local \(preparation.modelName)"
        case .transcribing:
            "Transcribing on this Mac"
        case .separatingSpeakers:
            "Separating speakers"
        case .buildingTranscript:
            "Building review transcript"
        }
    }

    var detail: String {
        switch self {
        case .preparingModel(let preparation):
            preparation.detail
        case .transcribing:
            "Running local speech recognition. Audio stays on this Mac."
        case .separatingSpeakers:
            "Identifying who spoke when with the local speaker model."
        case .buildingTranscript:
            "Aligning words and speakers for review."
        }
    }

    var fractionCompleted: Double? {
        guard case .preparingModel(let preparation) = self else { return nil }
        return preparation.fractionCompleted
    }
}

struct ConversationTranscriptAttachment: Equatable, Sendable {
    static let mimeType = "text/markdown"

    var filename: String
    var data: Data
}

enum ConversationTranscriptMarkdown {
    static func attachment(for draft: ConversationTranscriptDraft) -> ConversationTranscriptAttachment {
        let timestamp = filenameTimestamp(draft.recordedAt)
        return ConversationTranscriptAttachment(
            filename: "conversation-transcript-\(timestamp).md",
            data: Data(render(draft).utf8)
        )
    }

    static func render(_ draft: ConversationTranscriptDraft) -> String {
        var lines = [
            "# Conversation transcript",
            "",
            "- Recorded: \(displayTimestamp(draft.recordedAt))",
            "- Team Room: \(escapeInline(draft.target.networkName)) / \(escapeInline(draft.target.threadName))",
            "- Duration: \(formatTime(draft.duration))",
            "- Transcription: local on-device model",
            "",
            "## Speakers",
            "",
        ]

        for speakerID in draft.orderedSpeakerIDs {
            let name = draft.speakerNames[speakerID] ?? speakerID
            lines.append("- \(escapeInline(name))")
        }

        lines.append(contentsOf: ["", "## Transcript", ""])
        for segment in draft.segments {
            let name = draft.speakerNames[segment.speakerID] ?? segment.speakerID
            lines.append("**[\(formatTime(segment.startTime))] \(escapeInline(name))**")
            lines.append("")
            lines.append(segment.text.trimmingCharacters(in: .whitespacesAndNewlines))
            lines.append("")
        }

        return lines.joined(separator: "\n").trimmingCharacters(in: .newlines) + "\n"
    }

    static func formatTime(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(seconds.rounded(.down)))
        let hours = total / 3_600
        let minutes = (total % 3_600) / 60
        let remainder = total % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, remainder)
        }
        return String(format: "%02d:%02d", minutes, remainder)
    }

    private static func displayTimestamp(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: date)
    }

    private static func filenameTimestamp(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd-HHmmss"
        return formatter.string(from: date)
    }

    private static func escapeInline(_ value: String) -> String {
        value.reduce(into: "") { result, character in
            if "\\`*_{}[]<>#|".contains(character) {
                result.append("\\")
            }
            result.append(character)
        }
    }
}
