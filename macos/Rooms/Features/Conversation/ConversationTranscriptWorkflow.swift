import Foundation
import Observation

@MainActor
@Observable
final class ConversationTranscriptWorkflow {
    enum Phase: Equatable {
        case idle
        case requestingPermission
        case recording(startedAt: Date)
        case transcribing(LocalTranscriptionStage)
        case review
        case uploading
        case attached(filename: String)
        case failed(message: String)
    }

    typealias AttachmentPoster = @MainActor (
        _ content: String,
        _ threadID: String,
        _ attachment: ConversationTranscriptAttachment
    ) async -> Bool

    private(set) var phase: Phase = .idle
    private(set) var target: ConversationTarget?
    private(set) var draft: ConversationTranscriptDraft?
    private(set) var recording: RecordedConversationAudio?
    private(set) var uploadError: String?

    private let recorder: any ConversationAudioCapturing
    private let transcriber: any ConversationTranscribing
    private let recordingsDirectory: URL
    private let now: @MainActor () -> Date
    private let makeIdentifier: @MainActor () -> String

    init(
        recorder: any ConversationAudioCapturing = MicrophoneConversationRecorder(),
        transcriber: any ConversationTranscribing = FluidConversationTranscriber(),
        recordingsDirectory: URL? = nil,
        now: @escaping @MainActor () -> Date = Date.init,
        makeIdentifier: @escaping @MainActor () -> String = { UUID().uuidString }
    ) {
        self.recorder = recorder
        self.transcriber = transcriber
        self.recordingsDirectory = recordingsDirectory ?? Self.defaultRecordingsDirectory
        self.now = now
        self.makeIdentifier = makeIdentifier
    }

    var canRetryTranscription: Bool {
        recording != nil
    }

    var isBusy: Bool {
        switch phase {
        case .requestingPermission, .transcribing, .uploading:
            true
        default:
            false
        }
    }

    func startRecording(target: ConversationTarget) async {
        guard !target.threadID.isEmpty else {
            phase = .failed(message: "Select a Team Room before recording.")
            return
        }
        guard phase == .idle || isFinished else { return }

        discardSavedRecording()
        draft = nil
        uploadError = nil
        self.target = target
        phase = .requestingPermission

        let startedAt = now()
        let fileURL = recordingsDirectory
            .appendingPathComponent("conversation-\(makeIdentifier())")
            .appendingPathExtension("wav")
        do {
            try await recorder.startRecording(to: fileURL, recordedAt: startedAt)
            phase = .recording(startedAt: startedAt)
        } catch {
            phase = .failed(message: error.localizedDescription)
        }
    }

    func stopAndTranscribe() async {
        guard case .recording = phase else { return }
        do {
            let recording = try recorder.stopRecording()
            self.recording = recording
            await transcribeSavedRecording(recording)
        } catch {
            phase = .failed(message: error.localizedDescription)
        }
    }

    func retryTranscription() async {
        guard let recording else { return }
        await transcribeSavedRecording(recording)
    }

    func renameSpeaker(_ speakerID: String, to name: String) {
        guard var updatedDraft = draft else { return }
        updatedDraft.speakerNames[speakerID] = name
        draft = updatedDraft
    }

    func addSpeaker() {
        guard var updatedDraft = draft else { return }
        var index = 1
        var id = "manual-\(index)"
        while updatedDraft.speakerNames[id] != nil {
            index += 1
            id = "manual-\(index)"
        }
        updatedDraft.speakerNames[id] = "Speaker \(updatedDraft.speakerNames.count + 1)"
        draft = updatedDraft
    }

    func assignSegment(_ segmentID: String, to speakerID: String) {
        guard var updatedDraft = draft,
              let index = updatedDraft.segments.firstIndex(where: { $0.id == segmentID })
        else {
            return
        }
        updatedDraft.segments[index].speakerID = speakerID
        draft = updatedDraft
    }

    func updateSegmentText(_ segmentID: String, text: String) {
        guard var updatedDraft = draft,
              let index = updatedDraft.segments.firstIndex(where: { $0.id == segmentID })
        else {
            return
        }
        updatedDraft.segments[index].text = text
        draft = updatedDraft
    }

    func markdownAttachment() -> ConversationTranscriptAttachment? {
        draft.map { ConversationTranscriptMarkdown.attachment(for: $0) }
    }

    func attach(using poster: AttachmentPoster) async {
        guard let target, let attachment = markdownAttachment() else { return }
        guard draft?.segments.contains(where: {
            !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }) == true else {
            uploadError = "The transcript has no text to attach."
            return
        }

        uploadError = nil
        phase = .uploading
        let content = "Conversation transcript recorded \(target.networkName) / \(target.threadName)"
        if await poster(content, target.threadID, attachment) {
            discardSavedRecording()
            phase = .attached(filename: attachment.filename)
        } else {
            uploadError = "The transcript could not be attached. Your review and recording are still available."
            phase = .review
        }
    }

    func saveMarkdown(to fileURL: URL) throws {
        guard let attachment = markdownAttachment() else { return }
        try attachment.data.write(to: fileURL, options: .atomic)
    }

    func discard() {
        recorder.cancelRecording()
        discardSavedRecording()
        target = nil
        draft = nil
        uploadError = nil
        phase = .idle
    }

    func cancelActiveRecordingForTermination() {
        recorder.cancelRecording()
        discardSavedRecording()
    }

    private var isFinished: Bool {
        if case .attached = phase { return true }
        if case .failed = phase, recording == nil { return true }
        return false
    }

    private func transcribeSavedRecording(_ recording: RecordedConversationAudio) async {
        phase = .transcribing(.preparingModel(.speechStarting))
        do {
            let local = try await transcriber.transcribe(recording) { [weak self] stage in
                await MainActor.run {
                    self?.phase = .transcribing(stage)
                }
            }
            guard !local.segments.isEmpty, let target else {
                throw LocalConversationTranscriptionError.emptyTranscript
            }

            var seen: Set<String> = []
            let speakerIDs = local.segments.compactMap { segment in
                seen.insert(segment.speakerID).inserted ? segment.speakerID : nil
            }
            let names = Dictionary(uniqueKeysWithValues: speakerIDs.enumerated().map {
                ($0.element, "Speaker \($0.offset + 1)")
            })
            draft = ConversationTranscriptDraft(
                recordedAt: recording.recordedAt,
                duration: recording.duration,
                target: target,
                segments: local.segments,
                speakerNames: names,
                usedSpeakerDiarization: local.usedSpeakerDiarization,
                speakerSeparationFallback: local.speakerSeparationFallback
            )
            phase = .review
        } catch {
            phase = .failed(message: error.localizedDescription)
        }
    }

    private func discardSavedRecording() {
        if let recording {
            try? FileManager.default.removeItem(at: recording.fileURL)
        }
        recording = nil
    }

    private static var defaultRecordingsDirectory: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("ai.archastro.Rooms", isDirectory: true)
            .appendingPathComponent("Recordings", isDirectory: true)
    }
}
