import AVFoundation
import Foundation

@MainActor
protocol ConversationAudioCapturing: AnyObject {
    func startRecording(to fileURL: URL, recordedAt: Date) async throws
    func stopRecording() throws -> RecordedConversationAudio
    func cancelRecording()
}

enum ConversationAudioCaptureError: LocalizedError {
    case microphonePermissionDenied
    case alreadyRecording
    case notRecording
    case recordingDidNotStart
    case noAudioCaptured

    var errorDescription: String? {
        switch self {
        case .microphonePermissionDenied:
            "Microphone access is required. Enable Rooms in System Settings → Privacy & Security → Microphone."
        case .alreadyRecording:
            "A conversation recording is already in progress."
        case .notRecording:
            "No conversation recording is in progress."
        case .recordingDidNotStart:
            "Rooms could not start the selected microphone."
        case .noAudioCaptured:
            "The recording did not contain any audio."
        }
    }
}

@MainActor
final class MicrophoneConversationRecorder: ConversationAudioCapturing {
    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private var recordingStartedAt: Date?

    func startRecording(to fileURL: URL, recordedAt: Date) async throws {
        guard recorder == nil else { throw ConversationAudioCaptureError.alreadyRecording }

        let permissionGranted = await AVAudioApplication.requestRecordPermission()
        guard permissionGranted else {
            throw ConversationAudioCaptureError.microphonePermissionDenied
        }

        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )

        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsFloatKey: false,
        ]
        let recorder = try AVAudioRecorder(url: fileURL, settings: settings)
        recorder.isMeteringEnabled = true
        guard recorder.prepareToRecord(), recorder.record() else {
            try? FileManager.default.removeItem(at: fileURL)
            throw ConversationAudioCaptureError.recordingDidNotStart
        }

        self.recorder = recorder
        recordingURL = fileURL
        recordingStartedAt = recordedAt
    }

    func stopRecording() throws -> RecordedConversationAudio {
        guard let recorder, let recordingURL, let recordingStartedAt else {
            throw ConversationAudioCaptureError.notRecording
        }
        let duration = recorder.currentTime
        recorder.stop()
        self.recorder = nil
        self.recordingURL = nil
        self.recordingStartedAt = nil

        let byteCount = (try? recordingURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        guard duration > 0, byteCount > 44 else {
            try? FileManager.default.removeItem(at: recordingURL)
            throw ConversationAudioCaptureError.noAudioCaptured
        }
        return RecordedConversationAudio(
            fileURL: recordingURL,
            duration: duration,
            recordedAt: recordingStartedAt
        )
    }

    func cancelRecording() {
        recorder?.stop()
        recorder = nil
        if let recordingURL {
            try? FileManager.default.removeItem(at: recordingURL)
        }
        recordingURL = nil
        recordingStartedAt = nil
    }
}
