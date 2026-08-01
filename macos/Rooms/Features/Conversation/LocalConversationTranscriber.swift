import FluidAudio
import Foundation

// FluidAudio documents that this manager's Core ML state is immutable after
// initialization and internally coordinates its detached inference tasks.
extension OfflineDiarizerManager: @retroactive @unchecked Sendable {}

protocol ConversationTranscribing: Sendable {
    func transcribe(
        _ recording: RecordedConversationAudio,
        onStage: @escaping @Sendable (LocalTranscriptionStage) async -> Void
    ) async throws -> LocalConversationTranscript
}

enum LocalConversationTranscriptionError: LocalizedError {
    case emptyTranscript

    var errorDescription: String? {
        switch self {
        case .emptyTranscript:
            "The local model did not detect any speech in this recording."
        }
    }
}

struct ModelPreparationProgressTracker: Sendable {
    private(set) var operationIndex = 1
    private var previousReportedFraction: Double?

    mutating func displayedFraction(for progress: DownloadProgress) -> Double {
        let reportedFraction = min(max(progress.fractionCompleted, 0), 1)
        if let previousReportedFraction,
           reportedFraction + 0.001 < previousReportedFraction
        {
            operationIndex += 1
        }
        previousReportedFraction = reportedFraction

        // FluidAudio reports progress independently for each model operation,
        // so 1.0 means the current component finished, not that the entire
        // speech or diarization model is ready. The outer stage transition is
        // the only truthful overall-completion signal.
        return min(reportedFraction, 0.99)
    }
}

/// Batch transcription is deliberate: the microphone is stopped before model
/// inference starts, and the recording never leaves this Mac. FluidAudio keeps
/// its Core ML models in Application Support after the first download.
actor FluidConversationTranscriber: ConversationTranscribing {
    private var asrManager: AsrManager?
    private var diarizer: OfflineDiarizerManager?

    func transcribe(
        _ recording: RecordedConversationAudio,
        onStage: @escaping @Sendable (LocalTranscriptionStage) async -> Void
    ) async throws -> LocalConversationTranscript {
        let asr = try await preparedASRManager(onStage: onStage)

        await onStage(.transcribing)
        var decoderState = TdtDecoderState.make(decoderLayers: await asr.decoderLayerCount)
        let result = try await asr.transcribe(
            recording.fileURL,
            decoderState: &decoderState
        )
        let transcriptText = result.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcriptText.isEmpty else {
            throw LocalConversationTranscriptionError.emptyTranscript
        }

        let words = result.tokenTimings.map { buildWordTimings(from: $0) } ?? []
        guard !words.isEmpty else {
            return LocalConversationTranscript(
                segments: [
                    ConversationTranscriptSegment(
                        id: "segment-1",
                        speakerID: "S1",
                        startTime: 0,
                        endTime: recording.duration,
                        text: transcriptText
                    )
                ],
                usedSpeakerDiarization: false,
                speakerSeparationFallback: .wordTimingsUnavailable
            )
        }

        let diarizationSegments: [TimedSpeakerSegment]
        let diarizationError: (any Error)?
        do {
            let diarizer = try await preparedDiarizer(onStage: onStage)
            await onStage(.separatingSpeakers)
            diarizationSegments = try await diarizer.process(recording.fileURL).segments
            diarizationError = nil
        } catch {
            // Diarization is additive. Preserve a useful local transcript and
            // let the review UI assign speakers when separation cannot run.
            diarizationSegments = []
            diarizationError = error
        }

        await onStage(.buildingTranscript)
        return Self.buildTranscript(
            words: words,
            diarizationSegments: diarizationSegments,
            diarizationError: diarizationError
        )
    }

    private func preparedASRManager(
        onStage: @escaping @Sendable (LocalTranscriptionStage) async -> Void
    ) async throws -> AsrManager {
        if let asrManager { return asrManager }
        await onStage(.preparingModel(.speechStarting))

        let (progressStream, progressContinuation) = AsyncStream<DownloadProgress>.makeStream(
            bufferingPolicy: .bufferingNewest(1)
        )
        let progressTask = Task {
            var tracker = ModelPreparationProgressTracker()
            for await progress in progressStream {
                await onStage(
                    .preparingModel(
                        Self.speechModelPreparation(
                            progress: progress,
                            displayedFraction: tracker.displayedFraction(for: progress)
                        )
                    )
                )
            }
        }

        let models: AsrModels
        do {
            models = try await AsrModels.downloadAndLoad(
                version: .v3,
                encoderPrecision: .int8,
                progressHandler: { progress in
                    progressContinuation.yield(progress)
                }
            )
        } catch {
            progressContinuation.finish()
            await progressTask.value
            throw error
        }
        progressContinuation.finish()
        await progressTask.value

        // v3 is multilingual; FluidAudio recommends disabling mel context for
        // long-form v3 audio to avoid wrong-language drift at chunk seams.
        let manager = AsrManager(config: ASRConfig(melChunkContext: false))
        try await manager.loadModels(models)
        asrManager = manager
        return manager
    }

    private func preparedDiarizer(
        onStage: @escaping @Sendable (LocalTranscriptionStage) async -> Void
    ) async throws -> OfflineDiarizerManager {
        if let diarizer { return diarizer }
        await onStage(.preparingModel(.speakerStarting))
        let manager = OfflineDiarizerManager(config: .default)

        let (progressStream, progressContinuation) = AsyncStream<DownloadProgress>.makeStream(
            bufferingPolicy: .bufferingNewest(1)
        )
        let progressTask = Task {
            var tracker = ModelPreparationProgressTracker()
            for await progress in progressStream {
                await onStage(
                    .preparingModel(
                        Self.speakerModelPreparation(
                            progress: progress,
                            displayedFraction: tracker.displayedFraction(for: progress)
                        )
                    )
                )
            }
        }

        let models: OfflineDiarizerModels
        do {
            models = try await OfflineDiarizerModels.load(
                progressHandler: { progress in
                    progressContinuation.yield(progress)
                }
            )
        } catch {
            progressContinuation.finish()
            await progressTask.value
            await onStage(
                .preparingModel(
                    LocalModelPreparation(
                        modelName: "speaker separation model",
                        fractionCompleted: nil,
                        detail: "Repairing the local speaker model cache."
                    )
                )
            )
            try await manager.prepareModels()
            diarizer = manager
            return manager
        }
        progressContinuation.finish()
        await progressTask.value

        manager.initialize(models: models)
        diarizer = manager
        return manager
    }

    static func speechModelPreparation(
        progress: DownloadProgress,
        displayedFraction: Double
    ) -> LocalModelPreparation {
        let detail: String
        switch progress.phase {
        case .listing:
            detail = "Checking local speech model files."
        case .downloading(let completedFiles, let totalFiles):
            if totalFiles > 0 {
                detail = "Downloading local speech model files \(completedFiles) of \(totalFiles)."
            } else {
                detail = "Using locally cached speech model files."
            }
        case .compiling(let modelName):
            detail = modelName.isEmpty
                ? "Local speech model is ready."
                : "Compiling \(modelName) for this Mac."
        }
        return LocalModelPreparation(
            modelName: "speech recognition model",
            fractionCompleted: min(max(displayedFraction, 0), 1),
            detail: detail
        )
    }

    static func speakerModelPreparation(
        progress: DownloadProgress,
        displayedFraction: Double
    ) -> LocalModelPreparation {
        let detail: String
        switch progress.phase {
        case .listing:
            detail = "Checking local speaker model files."
        case .downloading(let completedFiles, let totalFiles):
            if totalFiles > 0 {
                detail = "Downloading local speaker model files \(completedFiles) of \(totalFiles)."
            } else {
                detail = "Using locally cached speaker model files."
            }
        case .compiling(let modelName):
            detail = modelName.isEmpty
                ? "Local speaker model is ready."
                : "Compiling \(modelName) for this Mac."
        }
        return LocalModelPreparation(
            modelName: "speaker separation model",
            fractionCompleted: min(max(displayedFraction, 0), 1),
            detail: detail
        )
    }

    private struct AssignedWord {
        var timing: WordTiming
        var speakerID: String
    }

    static func buildTranscript(
        words: [WordTiming],
        diarizationSegments: [TimedSpeakerSegment],
        diarizationError: (any Error)?
    ) -> LocalConversationTranscript {
        let fallback = diarizationError.map { speakerSeparationFallback(for: $0) }
            ?? (diarizationSegments.isEmpty ? .insufficientSpeech : nil)
        return LocalConversationTranscript(
            segments: buildSegments(
                words: words,
                diarizationSegments: diarizationSegments
            ),
            usedSpeakerDiarization: !diarizationSegments.isEmpty,
            speakerSeparationFallback: fallback
        )
    }

    static func speakerSeparationFallback(
        for error: any Error
    ) -> SpeakerSeparationFallbackReason {
        if let error = error as? OfflineDiarizationError {
            switch error {
            case .noSpeechDetected:
                return .insufficientSpeech
            case .modelNotLoaded:
                return .modelUnavailable
            case .invalidConfiguration, .invalidBatchSize, .processingFailed, .exportFailed:
                return .processingFailed
            }
        }
        if error is DownloadError {
            return .modelUnavailable
        }
        return .processingFailed
    }

    static func buildSegments(
        words: [WordTiming],
        diarizationSegments: [TimedSpeakerSegment]
    ) -> [ConversationTranscriptSegment] {
        var previousSpeaker = diarizationSegments.first?.speakerId ?? "S1"
        let assigned = words.map { word -> AssignedWord in
            let speaker = bestSpeaker(
                for: word,
                in: diarizationSegments,
                fallback: previousSpeaker
            )
            previousSpeaker = speaker
            return AssignedWord(timing: word, speakerID: speaker)
        }

        var groups: [[AssignedWord]] = []
        for word in assigned {
            if let lastWord = groups.last?.last,
               lastWord.speakerID == word.speakerID,
               word.timing.startTime - lastWord.timing.endTime <= 1.5
            {
                groups[groups.count - 1].append(word)
            } else {
                groups.append([word])
            }
        }

        return groups.enumerated().compactMap { index, group in
            guard let first = group.first, let last = group.last else { return nil }
            return ConversationTranscriptSegment(
                id: "segment-\(index + 1)",
                speakerID: first.speakerID,
                startTime: first.timing.startTime,
                endTime: last.timing.endTime,
                text: joinedWords(group.map(\.timing.word))
            )
        }
    }

    private static func bestSpeaker(
        for word: WordTiming,
        in segments: [TimedSpeakerSegment],
        fallback: String
    ) -> String {
        guard !segments.isEmpty else { return fallback }
        let wordStart = word.startTime
        let wordEnd = word.endTime
        let overlapping = segments.map { segment in
            let start = Double(segment.startTimeSeconds)
            let end = Double(segment.endTimeSeconds)
            return (segment, max(0, min(wordEnd, end) - max(wordStart, start)))
        }
        if let match = overlapping.max(by: { $0.1 < $1.1 }), match.1 > 0 {
            return match.0.speakerId
        }

        let midpoint = (wordStart + wordEnd) / 2
        return segments.min { lhs, rhs in
            distance(from: midpoint, to: lhs) < distance(from: midpoint, to: rhs)
        }?.speakerId ?? fallback
    }

    private static func distance(
        from time: TimeInterval,
        to segment: TimedSpeakerSegment
    ) -> TimeInterval {
        let start = Double(segment.startTimeSeconds)
        let end = Double(segment.endTimeSeconds)
        if time < start { return start - time }
        if time > end { return time - end }
        return 0
    }

    private static func joinedWords(_ words: [String]) -> String {
        let punctuation = CharacterSet(charactersIn: ".,!?;:%)]}’")
        return words.reduce(into: "") { result, word in
            guard !word.isEmpty else { return }
            let beginsWithPunctuation = word.unicodeScalars.first.map {
                punctuation.contains($0)
            } ?? false
            if !result.isEmpty && !beginsWithPunctuation {
                result.append(" ")
            }
            result.append(word)
        }
    }
}
