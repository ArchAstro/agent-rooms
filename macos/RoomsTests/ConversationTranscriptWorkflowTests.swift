import Foundation
import Testing
import ArchAstroPlatform
import FluidAudio
@testable import Rooms

@Suite struct ConversationTranscriptWorkflowTests {
    @Test @MainActor
    func recorded_conversation_is_transcribed_reviewed_and_attached_to_the_selected_team_room() async throws {
        // Set up an app-owned recording directory and deterministic local boundaries so
        // the user-visible scenario remains readable without microphone or model downloads.
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-conversation-test-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        let recordedAt = Date(timeIntervalSince1970: 1_785_535_200)
        let recorder = FakeConversationRecorder(duration: 17, startedAt: recordedAt)
        let transcriber = FakeConversationTranscriber(
            transcript: LocalConversationTranscript(
                segments: [
                    ConversationTranscriptSegment(
                        id: "segment-1",
                        speakerID: "S1",
                        startTime: 0,
                        endTime: 4.2,
                        text: "We should ship the local transcript flow."
                    ),
                    ConversationTranscriptSegment(
                        id: "segment-2",
                        speakerID: "S2",
                        startTime: 4.4,
                        endTime: 8.7,
                        text: "I will verify the attachment boundary."
                    ),
                ],
                usedSpeakerDiarization: true
            )
        )
        let workflow = ConversationTranscriptWorkflow(
            recorder: recorder,
            transcriber: transcriber,
            recordingsDirectory: recordingsDirectory,
            makeIdentifier: { "workflow-integration" }
        )
        let target = ConversationTarget(
            networkName: "ArchAstro",
            threadName: "Team Room",
            threadID: "thread-captured-at-start"
        )

        // Exercise production workflow coordination with deterministic recording/model
        // adapters. The opt-in live account smoke covers the real Team Room network boundary;
        // microphone and Core ML execution still require a manual hardware run.
        workflow.setConsentConfirmed(true)
        await workflow.startRecording(target: target)
        #expect(workflow.phase == .recording(startedAt: recordedAt))
        let recordingURL = try #require(recorder.recordingURL)
        #expect(FileManager.default.fileExists(atPath: recordingURL.path))
        await workflow.stopAndTranscribe()
        #expect(workflow.phase == .review)
        let receivedRecordingURL = await transcriber.receivedRecordingURL
        #expect(receivedRecordingURL == recordingURL)

        // Apply the reviewer's global speaker names and a transcript correction before
        // anything crosses the Team Room attachment boundary.
        workflow.renameSpeaker("S1", to: "Calvin")
        workflow.renameSpeaker("S2", to: "Bruno")
        workflow.addSpeaker()
        workflow.renameSpeaker("manual-1", to: "Ada")
        workflow.assignSegment("segment-2", to: "manual-1")
        workflow.updateSegmentText(
            "segment-2",
            text: "I verified the Markdown attachment boundary."
        )
        let exportedURL = recordingsDirectory.appendingPathComponent("reviewed-transcript.md")
        try workflow.saveMarkdown(to: exportedURL)

        var postedContent: String?
        var postedThreadID: String?
        var postedAttachment: ConversationTranscriptAttachment?
        await workflow.attach { content, threadID, attachment, _ in
            postedContent = content
            postedThreadID = threadID
            postedAttachment = attachment
            return true
        }

        // Verify externally observable output: the originally selected room receives a
        // Markdown file containing reviewed names/text, and retained source audio is gone.
        #expect(postedContent == "Conversation transcript recorded ArchAstro / Team Room")
        #expect(postedThreadID == "thread-captured-at-start")
        let attachment = try #require(postedAttachment)
        #expect(attachment.filename == "conversation-transcript-2026-07-31-220000.md")
        let markdown = try #require(String(data: attachment.data, encoding: .utf8))
        let exportedData = try Data(contentsOf: exportedURL)
        #expect(exportedData == attachment.data)
        #expect(markdown.contains("**[00:00] Calvin**"))
        #expect(markdown.contains("**[00:04] Ada**"))
        #expect(markdown.contains("I verified the Markdown attachment boundary."))
        #expect(workflow.phase == .attached(filename: attachment.filename))
        #expect(!FileManager.default.fileExists(atPath: recordingURL.path))
    }

    @Test @MainActor
    func failed_attachment_keeps_the_review_and_audio_for_retry() async throws {
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-conversation-retry-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        let recorder = FakeConversationRecorder(duration: 3)
        let transcriber = FakeConversationTranscriber(
            transcript: LocalConversationTranscript(
                segments: [
                    ConversationTranscriptSegment(
                        id: "segment-1",
                        speakerID: "S1",
                        startTime: 0,
                        endTime: 2,
                        text: "Keep this review for retry."
                    )
                ],
                usedSpeakerDiarization: false
            )
        )
        let workflow = ConversationTranscriptWorkflow(
            recorder: recorder,
            transcriber: transcriber,
            recordingsDirectory: recordingsDirectory
        )
        let target = ConversationTarget(
            networkName: "ArchAstro",
            threadName: "Team Room",
            threadID: "thread-retry"
        )

        workflow.setConsentConfirmed(true)
        await workflow.startRecording(target: target)
        let recordingURL = try #require(recorder.recordingURL)
        await workflow.stopAndTranscribe()
        await workflow.attach { _, _, _, _ in false }

        #expect(workflow.phase == .review)
        #expect(workflow.uploadError != nil)
        #expect(workflow.draft?.segments.first?.text == "Keep this review for retry.")
        #expect(FileManager.default.fileExists(atPath: recordingURL.path))
    }

    @Test @MainActor
    func adding_speakers_updates_the_review_without_overlapping_draft_access() async throws {
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-speaker-regression-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        let workflow = ConversationTranscriptWorkflow(
            recorder: FakeConversationRecorder(duration: 2),
            transcriber: FakeConversationTranscriber(
                transcript: LocalConversationTranscript(
                    segments: [
                        ConversationTranscriptSegment(
                            id: "segment-1",
                            speakerID: "S1",
                            startTime: 0,
                            endTime: 1,
                            text: "Initial speaker."
                        )
                    ],
                    usedSpeakerDiarization: true
                )
            ),
            recordingsDirectory: recordingsDirectory
        )
        let target = ConversationTarget(
            networkName: "ArchAstro",
            threadName: "Team Room",
            threadID: "thread-speaker-regression"
        )

        workflow.setConsentConfirmed(true)
        await workflow.startRecording(target: target)
        await workflow.stopAndTranscribe()
        workflow.addSpeaker()
        workflow.addSpeaker()

        #expect(workflow.draft?.speakerNames["manual-1"] == "Speaker 2")
        #expect(workflow.draft?.speakerNames["manual-2"] == "Speaker 3")
        #expect(workflow.draft?.orderedSpeakerIDs == ["S1", "manual-1", "manual-2"])
    }

    @Test @MainActor
    func failed_transcription_retains_audio_and_retry_reaches_review() async throws {
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-transcription-retry-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        let recorder = FakeConversationRecorder(duration: 4)
        let transcriber = FailOnceConversationTranscriber(
            transcript: LocalConversationTranscript(
                segments: [
                    ConversationTranscriptSegment(
                        id: "segment-1",
                        speakerID: "S1",
                        startTime: 0,
                        endTime: 3,
                        text: "The retry used the retained recording."
                    )
                ],
                usedSpeakerDiarization: false,
                speakerSeparationFallback: .insufficientSpeech
            )
        )
        let workflow = ConversationTranscriptWorkflow(
            recorder: recorder,
            transcriber: transcriber,
            recordingsDirectory: recordingsDirectory
        )
        let target = ConversationTarget(
            networkName: "ArchAstro",
            threadName: "Team Room",
            threadID: "thread-transcription-retry"
        )

        workflow.setConsentConfirmed(true)
        await workflow.startRecording(target: target)
        let recordingURL = try #require(recorder.recordingURL)
        await workflow.stopAndTranscribe()

        guard case .failed(let message) = workflow.phase else {
            Issue.record("Expected the first transcription attempt to fail")
            return
        }
        #expect(message == TestTranscriptionError.firstAttempt.localizedDescription)
        #expect(workflow.canRetryTranscription)
        #expect(FileManager.default.fileExists(atPath: recordingURL.path))

        await workflow.retryTranscription()

        #expect(workflow.phase == .review)
        #expect(workflow.draft?.segments.first?.text == "The retry used the retained recording.")
        let receivedRecordingURLs = await transcriber.receivedRecordingURLs
        #expect(receivedRecordingURLs == [recordingURL, recordingURL])

        workflow.discard()
        #expect(workflow.phase == .idle)
        #expect(!FileManager.default.fileExists(atPath: recordingURL.path))
    }

    @Test func multi_component_model_progress_does_not_reach_100_percent_early() {
        var tracker = ModelPreparationProgressTracker()
        let reported = [
            DownloadProgress(
                fractionCompleted: 0.8,
                phase: .downloading(completedFiles: 4, totalFiles: 5)
            ),
            DownloadProgress(
                fractionCompleted: 1,
                phase: .compiling(modelName: "")
            ),
            DownloadProgress(
                fractionCompleted: 0.1,
                phase: .downloading(completedFiles: 1, totalFiles: 10)
            ),
            DownloadProgress(
                fractionCompleted: 0.65,
                phase: .downloading(completedFiles: 6, totalFiles: 10)
            ),
        ]

        let displayed = reported.map { tracker.displayedFraction(for: $0) }

        #expect(displayed == [0.8, 0.99, 0.1, 0.65])
        #expect(displayed.allSatisfy { $0 < 1 })
        #expect(tracker.operationIndex == 2)
    }

    @Test func model_download_progress_is_exposed_for_speech_and_speaker_models() {
        let speechProgress = DownloadProgress(
            fractionCompleted: 0.42,
            phase: .downloading(completedFiles: 2, totalFiles: 5)
        )
        let speechPreparation = FluidConversationTranscriber.speechModelPreparation(
            progress: speechProgress,
            displayedFraction: speechProgress.fractionCompleted
        )
        let speechStage = LocalTranscriptionStage.preparingModel(speechPreparation)
        let speakerProgress = DownloadProgress(
            fractionCompleted: 0.75,
            phase: .compiling(modelName: "speaker-embedding.mlmodelc")
        )
        let speakerPreparation = FluidConversationTranscriber.speakerModelPreparation(
            progress: speakerProgress,
            displayedFraction: speakerProgress.fractionCompleted
        )
        let speakerStage = LocalTranscriptionStage.preparingModel(speakerPreparation)
        let terminalProgress = DownloadProgress(
            fractionCompleted: 1,
            phase: .compiling(modelName: "")
        )
        let speechTerminal = FluidConversationTranscriber.speechModelPreparation(
            progress: terminalProgress,
            displayedFraction: 0.99
        )
        let speakerTerminal = FluidConversationTranscriber.speakerModelPreparation(
            progress: terminalProgress,
            displayedFraction: 0.99
        )

        #expect(speechStage.fractionCompleted == 0.42)
        #expect(speechStage.label == "Preparing local speech recognition model")
        #expect(speechStage.detail == "Downloading local speech model files 2 of 5.")
        #expect(speakerStage.fractionCompleted == 0.75)
        #expect(speakerStage.label == "Preparing local speaker separation model")
        #expect(speakerStage.detail == "Compiling speaker-embedding.mlmodelc for this Mac.")
        #expect(speechTerminal.detail == "Finishing this local speech model step.")
        #expect(speakerTerminal.detail == "Finishing this local speaker model step.")
    }

    @Test func word_timings_are_grouped_by_the_diarized_speaker() {
        let words = [
            WordTiming(word: "Hello", startTime: 0, endTime: 0.4),
            WordTiming(word: "there.", startTime: 0.5, endTime: 0.9),
            WordTiming(word: "Welcome", startTime: 1, endTime: 1.4),
            WordTiming(word: "back.", startTime: 1.5, endTime: 1.9),
        ]
        let diarization = [
            TimedSpeakerSegment(
                speakerId: "speaker-a",
                embedding: [],
                startTimeSeconds: 0,
                endTimeSeconds: 0.95,
                qualityScore: 1
            ),
            TimedSpeakerSegment(
                speakerId: "speaker-b",
                embedding: [],
                startTimeSeconds: 0.95,
                endTimeSeconds: 2,
                qualityScore: 1
            ),
        ]

        let segments = FluidConversationTranscriber.buildSegments(
            words: words,
            diarizationSegments: diarization
        )

        #expect(segments.map(\.speakerID) == ["speaker-a", "speaker-b"])
        #expect(segments.map(\.text) == ["Hello there.", "Welcome back."])
    }

    @Test func missing_diarization_falls_back_to_one_reviewable_speaker() {
        let segments = FluidConversationTranscriber.buildSegments(
            words: [
                WordTiming(word: "One", startTime: 0, endTime: 0.3),
                WordTiming(word: "speaker.", startTime: 0.4, endTime: 0.8),
            ],
            diarizationSegments: []
        )

        #expect(segments.count == 1)
        #expect(segments.first?.speakerID == "S1")
        #expect(segments.first?.text == "One speaker.")
    }

    @Test func diarization_failure_preserves_transcript_with_a_specific_fallback_reason() {
        let words = [
            WordTiming(word: "Keep", startTime: 0, endTime: 0.3),
            WordTiming(word: "the", startTime: 0.4, endTime: 0.6),
            WordTiming(word: "transcript.", startTime: 0.7, endTime: 1.1),
        ]

        let insufficientSpeech = FluidConversationTranscriber.buildTranscript(
            words: words,
            diarizationSegments: [],
            diarizationError: OfflineDiarizationError.noSpeechDetected
        )
        let unavailableModel = FluidConversationTranscriber.buildTranscript(
            words: words,
            diarizationSegments: [],
            diarizationError: OfflineDiarizationError.modelNotLoaded("speaker-embedding")
        )

        #expect(insufficientSpeech.segments.map(\.text) == ["Keep the transcript."])
        #expect(unavailableModel.segments == insufficientSpeech.segments)
        #expect(!insufficientSpeech.usedSpeakerDiarization)
        #expect(!unavailableModel.usedSpeakerDiarization)
        #expect(insufficientSpeech.speakerSeparationFallback == .insufficientSpeech)
        #expect(unavailableModel.speakerSeparationFallback == .modelUnavailable)
        #expect(
            insufficientSpeech.speakerSeparationFallback?.reviewMessage
                != unavailableModel.speakerSeparationFallback?.reviewMessage
        )
    }

    @Test func model_progress_and_diarization_failure_cross_the_production_transcriber_seams() async throws {
        let stages = TranscriptionStageRecorder()
        let transcriber = FluidConversationTranscriber(
            modelServer: FailingDiarizationModelServer()
        )
        let recording = RecordedConversationAudio(
            fileURL: URL(fileURLWithPath: "/tmp/rooms-production-seam.wav"),
            duration: 2,
            recordedAt: Date(timeIntervalSince1970: 1_785_535_200)
        )

        let transcript = try await transcriber.transcribe(recording) { stage in
            await stages.append(stage)
        }
        let emittedStages = await stages.stages
        let preparations = emittedStages.compactMap { stage -> LocalModelPreparation? in
            guard case .preparingModel(let preparation) = stage else { return nil }
            return preparation
        }

        #expect(
            preparations.contains {
                $0.modelName == "speech recognition model"
                    && $0.operationIndex == 2
                    && $0.fractionCompleted == 0.1
            }
        )
        #expect(
            preparations.contains {
                $0.modelName == "speaker separation model" && $0.fractionCompleted == 0.75
            }
        )
        let finalSpeakerPreparation = preparations.last {
            $0.modelName == "speaker separation model"
        }
        #expect(finalSpeakerPreparation?.fractionCompleted == nil)
        #expect(finalSpeakerPreparation?.detail == "Repairing the local speaker model cache.")
        #expect(
            LocalTranscriptionStage.preparingModel(
                LocalModelPreparation(
                    modelName: "speech recognition model",
                    fractionCompleted: 0.1,
                    detail: "Downloading another model component.",
                    operationIndex: 2
                )
            ).progressLabel == "Model step 2 · 10%"
        )
        #expect(emittedStages.contains(.separatingSpeakers))
        #expect(emittedStages.last == .buildingTranscript)
        #expect(transcript.segments.map(\.text) == ["Keep the local transcript."])
        #expect(!transcript.usedSpeakerDiarization)
        #expect(transcript.speakerSeparationFallback == .insufficientSpeech)
    }

    @Test @MainActor
    func recorder_reported_capture_time_excludes_the_permission_prompt_delay() async throws {
        let actualCaptureStart = Date(timeIntervalSince1970: 1_785_535_260)
        let workflow = ConversationTranscriptWorkflow(
            recorder: FakeConversationRecorder(
                duration: 2,
                startedAt: actualCaptureStart,
                startDelay: .milliseconds(5)
            ),
            transcriber: FakeConversationTranscriber(
                transcript: LocalConversationTranscript(
                    segments: [],
                    usedSpeakerDiarization: false
                )
            ),
            recordingsDirectory: FileManager.default.temporaryDirectory
                .appendingPathComponent("rooms-capture-time-\(UUID().uuidString)")
        )
        defer { workflow.discard() }
        workflow.setConsentConfirmed(true)

        await workflow.startRecording(
            target: ConversationTarget(
                networkName: "ArchAstro",
                threadName: "Team Room",
                threadID: "thread-capture-time"
            )
        )

        #expect(workflow.phase == .recording(startedAt: actualCaptureStart))
    }

    @Test @MainActor
    func closing_the_conversation_requires_fresh_consent_before_another_recording() async {
        let workflow = ConversationTranscriptWorkflow(
            recorder: FakeConversationRecorder(duration: 2),
            transcriber: FakeConversationTranscriber(
                transcript: LocalConversationTranscript(segments: [], usedSpeakerDiarization: false)
            ),
            recordingsDirectory: FileManager.default.temporaryDirectory
                .appendingPathComponent("rooms-consent-reset-\(UUID().uuidString)")
        )
        let target = ConversationTarget(
            networkName: "ArchAstro",
            threadName: "Team Room",
            threadID: "thread-consent-reset"
        )

        workflow.setConsentConfirmed(true)
        workflow.resetConsent()
        await workflow.startRecording(target: target)
        #expect(
            workflow.phase
                == .failed(message: "Confirm that everyone knows the conversation is being recorded.")
        )

        workflow.setConsentConfirmed(true)
        await workflow.startRecording(target: target)
        guard case .recording = workflow.phase else {
            Issue.record("Expected fresh consent to allow recording")
            return
        }
        workflow.discard()
    }

    @Test @MainActor
    func attachment_retry_reuses_its_key_until_the_reviewed_payload_changes() async throws {
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-idempotency-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        let workflow = ConversationTranscriptWorkflow(
            recorder: FakeConversationRecorder(duration: 2),
            transcriber: FakeConversationTranscriber(
                transcript: LocalConversationTranscript(
                    segments: [
                        ConversationTranscriptSegment(
                            id: "segment-1",
                            speakerID: "S1",
                            startTime: 0,
                            endTime: 1,
                            text: "Original review."
                        )
                    ],
                    usedSpeakerDiarization: false
                )
            ),
            recordingsDirectory: recordingsDirectory
        )
        workflow.setConsentConfirmed(true)
        await workflow.startRecording(
            target: ConversationTarget(
                networkName: "ArchAstro",
                threadName: "Team Room",
                threadID: "thread-idempotency"
            )
        )
        await workflow.stopAndTranscribe()

        var keys: [String] = []
        await workflow.attach { _, _, _, key in
            keys.append(key)
            return false
        }
        await workflow.attach { _, _, _, key in
            keys.append(key)
            return false
        }
        workflow.updateSegmentText("segment-1", text: "Corrected review.")
        await workflow.attach { _, _, _, key in
            keys.append(key)
            return false
        }
        await workflow.attach { _, _, _, key in
            keys.append(key)
            return true
        }

        #expect(keys.count == 4)
        #expect(keys[0] == keys[1])
        #expect(keys[1] != keys[2])
        #expect(keys[2] == keys[3])
    }

    @Test @MainActor
    func quitting_rooms_deletes_session_audio_that_cannot_be_recovered_after_restart() async throws {
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-termination-cleanup-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        let recorder = FakeConversationRecorder(duration: 2)
        let workflow = ConversationTranscriptWorkflow(
            recorder: recorder,
            transcriber: FakeConversationTranscriber(
                transcript: LocalConversationTranscript(
                    segments: [
                        ConversationTranscriptSegment(
                            id: "segment-1",
                            speakerID: "S1",
                            startTime: 0,
                            endTime: 1,
                            text: "Session-only retry."
                        )
                    ],
                    usedSpeakerDiarization: false
                )
            ),
            recordingsDirectory: recordingsDirectory
        )
        workflow.setConsentConfirmed(true)
        await workflow.startRecording(
            target: ConversationTarget(
                networkName: "ArchAstro",
                threadName: "Team Room",
                threadID: "thread-termination"
            )
        )
        let recordingURL = try #require(recorder.recordingURL)
        await workflow.stopAndTranscribe()
        #expect(FileManager.default.fileExists(atPath: recordingURL.path))

        workflow.endSessionForTermination()

        #expect(!FileManager.default.fileExists(atPath: recordingURL.path))
        #expect(workflow.recording == nil)
        #expect(!workflow.consentConfirmed)
    }

    @Test @MainActor
    func stale_app_owned_recordings_are_removed_when_the_next_session_starts() throws {
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-stale-recording-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        try FileManager.default.createDirectory(
            at: recordingsDirectory,
            withIntermediateDirectories: true
        )
        let staleRecording = recordingsDirectory.appendingPathComponent("conversation-crashed.wav")
        let unrelatedRecording = recordingsDirectory.appendingPathComponent("interview.wav")
        try Data(repeating: 1, count: 128).write(to: staleRecording)
        try Data(repeating: 1, count: 128).write(to: unrelatedRecording)

        _ = ConversationTranscriptWorkflow(
            recorder: FakeConversationRecorder(duration: 2),
            transcriber: FakeConversationTranscriber(
                transcript: LocalConversationTranscript(segments: [], usedSpeakerDiarization: false)
            ),
            recordingsDirectory: recordingsDirectory
        )

        #expect(!FileManager.default.fileExists(atPath: staleRecording.path))
        #expect(FileManager.default.fileExists(atPath: unrelatedRecording.path))
    }

    @Test @MainActor
    func consent_revoked_while_permission_is_pending_prevents_hidden_recording() async throws {
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-pending-consent-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        let recorder = SuspendedStartConversationRecorder(
            startedAt: Date(timeIntervalSince1970: 1_785_535_260)
        )
        let workflow = ConversationTranscriptWorkflow(
            recorder: recorder,
            transcriber: FakeConversationTranscriber(
                transcript: LocalConversationTranscript(segments: [], usedSpeakerDiarization: false)
            ),
            recordingsDirectory: recordingsDirectory
        )
        workflow.setConsentConfirmed(true)
        let startTask = Task {
            await workflow.startRecording(
                target: ConversationTarget(
                    networkName: "ArchAstro",
                    threadName: "Team Room",
                    threadID: "thread-pending-consent"
                )
            )
        }
        while !recorder.isWaitingForPermissionResult {
            await Task.yield()
        }

        workflow.resetConsent()
        recorder.finishPermissionRequest()
        await startTask.value

        #expect(workflow.phase == .idle)
        #expect(recorder.captureStartCount == 0)
        #expect(recorder.cancelCount == 0)
        #expect(recorder.recordingURL == nil)
    }

    @Test @MainActor
    func denied_microphone_permission_never_starts_capture() async {
        let recorder = FakeConversationRecorder(duration: 2, permissionGranted: false)
        let workflow = ConversationTranscriptWorkflow(
            recorder: recorder,
            transcriber: FakeConversationTranscriber(
                transcript: LocalConversationTranscript(segments: [], usedSpeakerDiarization: false)
            ),
            recordingsDirectory: FileManager.default.temporaryDirectory
                .appendingPathComponent("rooms-permission-denied-\(UUID().uuidString)")
        )
        workflow.setConsentConfirmed(true)

        await workflow.startRecording(
            target: ConversationTarget(
                networkName: "ArchAstro",
                threadName: "Team Room",
                threadID: "thread-permission-denied"
            )
        )

        #expect(
            workflow.phase
                == .failed(
                    message: ConversationAudioCaptureError.microphonePermissionDenied
                        .localizedDescription
                )
        )
        #expect(recorder.recordingURL == nil)
    }

    @Test @MainActor
    func attachment_post_is_single_flight_while_the_first_result_is_pending() async throws {
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-attachment-single-flight-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        let workflow = ConversationTranscriptWorkflow(
            recorder: FakeConversationRecorder(duration: 2),
            transcriber: FakeConversationTranscriber(
                transcript: LocalConversationTranscript(
                    segments: [
                        ConversationTranscriptSegment(
                            id: "segment-1",
                            speakerID: "S1",
                            startTime: 0,
                            endTime: 1,
                            text: "Post once."
                        )
                    ],
                    usedSpeakerDiarization: false
                )
            ),
            recordingsDirectory: recordingsDirectory
        )
        workflow.setConsentConfirmed(true)
        await workflow.startRecording(
            target: ConversationTarget(
                networkName: "ArchAstro",
                threadName: "Team Room",
                threadID: "thread-single-flight"
            )
        )
        await workflow.stopAndTranscribe()
        let poster = SuspendedAttachmentPoster()

        let firstAttach = Task {
            await workflow.attach { _, _, _, key in
                await poster.post(idempotencyKey: key)
            }
        }
        while await poster.callCount == 0 {
            await Task.yield()
        }
        let secondAttach = Task {
            await workflow.attach { _, _, _, key in
                await poster.post(idempotencyKey: key)
            }
        }
        await Task.yield()

        let callsWhilePending = await poster.callCount
        #expect(callsWhilePending == 1)
        await poster.resolve(true)
        await firstAttach.value
        await secondAttach.value
        guard case .attached = workflow.phase else {
            Issue.record("Expected the first successful attachment to remain final")
            return
        }
    }

    @Test @MainActor
    func transcription_retry_is_single_flight_while_model_work_is_pending() async throws {
        let recordingsDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rooms-retry-single-flight-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: recordingsDirectory) }
        let transcriber = SuspendedRetryConversationTranscriber()
        let workflow = ConversationTranscriptWorkflow(
            recorder: FakeConversationRecorder(duration: 2),
            transcriber: transcriber,
            recordingsDirectory: recordingsDirectory
        )
        workflow.setConsentConfirmed(true)
        await workflow.startRecording(
            target: ConversationTarget(
                networkName: "ArchAstro",
                threadName: "Team Room",
                threadID: "thread-retry-single-flight"
            )
        )
        await workflow.stopAndTranscribe()
        guard case .failed = workflow.phase else {
            Issue.record("Expected the first transcription to fail")
            return
        }

        let firstRetry = Task { await workflow.retryTranscription() }
        while await transcriber.callCount < 2 {
            await Task.yield()
        }
        let secondRetry = Task { await workflow.retryTranscription() }
        await Task.yield()

        let callsWhilePending = await transcriber.callCount
        #expect(callsWhilePending == 2)
        await transcriber.resolveRetry()
        await firstRetry.value
        await secondRetry.value
        #expect(workflow.phase == .review)
    }

    @Test func message_upload_encodes_the_channel_attachment_contract() throws {
        let upload = MessageUpload(
            name: "conversation.md",
            mimeType: "text/markdown",
            data: Data("# Conversation\n".utf8)
        )

        #expect(upload.channelPayload["name"]?.stringValue == "conversation.md")
        #expect(upload.channelPayload["mime_type"]?.stringValue == "text/markdown")
        #expect(
            upload.channelPayload["content"]?.stringValue
                == Data("# Conversation\n".utf8).base64EncodedString()
        )
    }
}

@MainActor
private final class FakeConversationRecorder: ConversationAudioCapturing {
    private let duration: TimeInterval
    private let startedAt: Date
    private let startDelay: Duration?
    private let permissionGranted: Bool
    private var recordedAt: Date?
    private(set) var recordingURL: URL?

    init(
        duration: TimeInterval,
        startedAt: Date = Date(timeIntervalSince1970: 1_785_535_200),
        startDelay: Duration? = nil,
        permissionGranted: Bool = true
    ) {
        self.duration = duration
        self.startedAt = startedAt
        self.startDelay = startDelay
        self.permissionGranted = permissionGranted
    }

    func requestPermission() async -> Bool {
        if let startDelay {
            try? await Task.sleep(for: startDelay)
        }
        return permissionGranted
    }

    func startRecording(to fileURL: URL) throws -> Date {
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data(repeating: 1, count: 128).write(to: fileURL)
        recordingURL = fileURL
        recordedAt = startedAt
        return startedAt
    }

    func stopRecording() throws -> RecordedConversationAudio {
        RecordedConversationAudio(
            fileURL: try #require(recordingURL),
            duration: duration,
            recordedAt: try #require(recordedAt)
        )
    }

    func cancelRecording() {
        if let recordingURL {
            try? FileManager.default.removeItem(at: recordingURL)
        }
        recordingURL = nil
        recordedAt = nil
    }
}

@MainActor
private final class SuspendedStartConversationRecorder: ConversationAudioCapturing {
    private let startedAt: Date
    private var permissionContinuation: CheckedContinuation<Bool, Never>?
    private(set) var recordingURL: URL?
    private(set) var cancelCount = 0
    private(set) var captureStartCount = 0

    init(startedAt: Date) {
        self.startedAt = startedAt
    }

    var isWaitingForPermissionResult: Bool {
        permissionContinuation != nil
    }

    func requestPermission() async -> Bool {
        return await withCheckedContinuation { continuation in
            permissionContinuation = continuation
        }
    }

    func finishPermissionRequest() {
        let continuation = permissionContinuation
        permissionContinuation = nil
        continuation?.resume(returning: true)
    }

    func startRecording(to fileURL: URL) throws -> Date {
        captureStartCount += 1
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data(repeating: 1, count: 128).write(to: fileURL)
        recordingURL = fileURL
        return startedAt
    }

    func stopRecording() throws -> RecordedConversationAudio {
        throw ConversationAudioCaptureError.notRecording
    }

    func cancelRecording() {
        cancelCount += 1
        if let recordingURL {
            try? FileManager.default.removeItem(at: recordingURL)
        }
    }
}

private actor SuspendedAttachmentPoster {
    private var continuations: [CheckedContinuation<Bool, Never>] = []
    private(set) var callCount = 0

    func post(idempotencyKey: String) async -> Bool {
        callCount += 1
        return await withCheckedContinuation { continuation in
            continuations.append(continuation)
        }
    }

    func resolve(_ result: Bool) {
        let pending = continuations
        continuations = []
        pending.forEach { $0.resume(returning: result) }
    }
}

private actor SuspendedRetryConversationTranscriber: ConversationTranscribing {
    private var continuations: [CheckedContinuation<Void, Never>] = []
    private(set) var callCount = 0

    func transcribe(
        _ recording: RecordedConversationAudio,
        onStage: @escaping @Sendable (LocalTranscriptionStage) async -> Void
    ) async throws -> LocalConversationTranscript {
        callCount += 1
        guard callCount > 1 else {
            throw TestTranscriptionError.firstAttempt
        }
        await withCheckedContinuation { continuation in
            continuations.append(continuation)
        }
        await onStage(.buildingTranscript)
        return LocalConversationTranscript(
            segments: [
                ConversationTranscriptSegment(
                    id: "segment-1",
                    speakerID: "S1",
                    startTime: 0,
                    endTime: 1,
                    text: "Only one retry completed."
                )
            ],
            usedSpeakerDiarization: false
        )
    }

    func resolveRetry() {
        let pending = continuations
        continuations = []
        pending.forEach { $0.resume() }
    }
}

private actor TranscriptionStageRecorder {
    private(set) var stages: [LocalTranscriptionStage] = []

    func append(_ stage: LocalTranscriptionStage) {
        stages.append(stage)
    }
}

private actor FailingDiarizationModelServer: ConversationModelServing {
    func prepareSpeechModel(progressHandler: @escaping ProgressHandler) async throws {
        progressHandler(
            DownloadProgress(
                fractionCompleted: 0.8,
                phase: .downloading(completedFiles: 4, totalFiles: 5)
            )
        )
        progressHandler(
            DownloadProgress(
                fractionCompleted: 1,
                phase: .compiling(modelName: "")
            )
        )
        progressHandler(
            DownloadProgress(
                fractionCompleted: 0.1,
                phase: .downloading(completedFiles: 1, totalFiles: 10)
            )
        )
    }

    func transcribeSpeech(_ fileURL: URL) async throws -> RecognizedConversationSpeech {
        RecognizedConversationSpeech(
            text: "Keep the local transcript.",
            words: [
                WordTiming(word: "Keep", startTime: 0, endTime: 0.2),
                WordTiming(word: "the", startTime: 0.3, endTime: 0.5),
                WordTiming(word: "local", startTime: 0.6, endTime: 0.9),
                WordTiming(word: "transcript.", startTime: 1, endTime: 1.4),
            ]
        )
    }

    func prepareSpeakerModel(
        progressHandler: @escaping ProgressHandler,
        onRepair: @escaping @Sendable () -> Void
    ) async throws {
        progressHandler(
            DownloadProgress(
                fractionCompleted: 0.75,
                phase: .compiling(modelName: "speaker-embedding.mlmodelc")
            )
        )
        await Task.yield()
        onRepair()
    }

    func separateSpeakers(_ fileURL: URL) async throws -> [TimedSpeakerSegment] {
        throw OfflineDiarizationError.noSpeechDetected
    }
}

private actor FakeConversationTranscriber: ConversationTranscribing {
    let transcript: LocalConversationTranscript
    private(set) var receivedRecordingURL: URL?

    init(transcript: LocalConversationTranscript) {
        self.transcript = transcript
    }

    func transcribe(
        _ recording: RecordedConversationAudio,
        onStage: @escaping @Sendable (LocalTranscriptionStage) async -> Void
    ) async throws -> LocalConversationTranscript {
        receivedRecordingURL = recording.fileURL
        await onStage(.transcribing)
        await onStage(.separatingSpeakers)
        await onStage(.buildingTranscript)
        return transcript
    }
}

private enum TestTranscriptionError: LocalizedError {
    case firstAttempt

    var errorDescription: String? {
        "The first local transcription attempt failed."
    }
}

private actor FailOnceConversationTranscriber: ConversationTranscribing {
    let transcript: LocalConversationTranscript
    private(set) var receivedRecordingURLs: [URL] = []

    init(transcript: LocalConversationTranscript) {
        self.transcript = transcript
    }

    func transcribe(
        _ recording: RecordedConversationAudio,
        onStage: @escaping @Sendable (LocalTranscriptionStage) async -> Void
    ) async throws -> LocalConversationTranscript {
        receivedRecordingURLs.append(recording.fileURL)
        guard receivedRecordingURLs.count > 1 else {
            throw TestTranscriptionError.firstAttempt
        }
        await onStage(.buildingTranscript)
        return transcript
    }
}
