import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ConversationReviewView: View {
    @Environment(AppState.self) private var appState
    @Bindable var workflow: ConversationTranscriptWorkflow
    var close: @MainActor () -> Void

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
        }
        .frame(minWidth: 700, idealWidth: 820, minHeight: 560, idealHeight: 680)
        .background(Theme.paper)
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(systemName: "waveform.badge.mic")
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(Theme.green)
            VStack(alignment: .leading, spacing: 2) {
                Text("Conversation transcript")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Theme.ink)
                Text(workflow.target.map {
                    "\($0.networkName) / \($0.threadName)"
                } ?? "Record, review, and attach to Team Room")
                .font(.system(size: 11))
                .foregroundStyle(Theme.muted)
            }
            Spacer()
            Button("Close", action: close)
                .buttonStyle(.bordered)
        }
        .padding(.horizontal, 22)
        .frame(height: 68)
        .background(Theme.surface)
    }

    @ViewBuilder
    private var content: some View {
        switch workflow.phase {
        case .idle:
            startView
        case .requestingPermission:
            progressView(
                title: "Waiting for microphone access",
                detail: "macOS may ask you to allow Rooms to use the microphone."
            )
        case .recording(let startedAt):
            recordingView(startedAt: startedAt)
        case .transcribing(let stage):
            progressView(
                title: stage.label,
                detail: stage.detail,
                fractionCompleted: stage.fractionCompleted,
                progressLabel: stage.progressLabel
            )
        case .review:
            reviewView
        case .uploading:
            progressView(
                title: "Attaching transcript",
                detail: "Uploading the reviewed Markdown file to Team Room."
            )
        case .attached(let filename):
            attachedView(filename: filename)
        case .failed(let message):
            failureView(message: message)
        }
    }

    private var startView: some View {
        VStack(alignment: .leading, spacing: 20) {
            Spacer()
            Label("Audio is transcribed locally", systemImage: "lock.shield")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Theme.ink)
            Text(
                "Rooms records the active microphone, then uses local Core ML models to transcribe speech and separate speakers. You can correct every name and transcript segment before anything is shared."
            )
            .font(.system(size: 13))
            .foregroundStyle(Theme.muted)
            .fixedSize(horizontal: false, vertical: true)

            if appState.isSignedIn {
                Label(
                    "Transcript destination: \(appState.selectedNetwork.name) / \(appState.selectedThread.title)",
                    systemImage: "number"
                )
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Theme.ink)
            } else {
                Label(
                    "Sign in to Rooms before recording.",
                    systemImage: "person.crop.circle.badge.exclamationmark"
                )
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.badgeRed)
            }

            Toggle(
                "Everyone knows this conversation is being recorded.",
                isOn: Binding(
                    get: { workflow.consentConfirmed },
                    set: { workflow.setConsentConfirmed($0) }
                )
            )
                .toggleStyle(.checkbox)
                .font(.system(size: 12, weight: .medium))

            HStack {
                Spacer()
                Button("Start recording") {
                    let target = ConversationTarget(
                        networkName: appState.selectedNetwork.name,
                        threadName: appState.selectedThread.title,
                        threadID: appState.selectedThread.id
                    )
                    Task { await workflow.startRecording(target: target) }
                }
                .buttonStyle(.borderedProminent)
                .tint(Theme.green)
                .disabled(
                    !workflow.consentConfirmed
                        || !appState.isSignedIn
                        || appState.selectedThread.id.isEmpty
                )
                .accessibilityIdentifier("conversation.start-recording")
            }
            Spacer()
        }
        .padding(36)
        .frame(maxWidth: 620)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func recordingView(startedAt: Date) -> some View {
        VStack(spacing: 24) {
            Spacer()
            ZStack {
                Circle().fill(Theme.badgeRed.opacity(0.14)).frame(width: 110, height: 110)
                Circle().fill(Theme.badgeRed).frame(width: 56, height: 56)
            }
            Text("Recording conversation")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Theme.ink)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(ConversationTranscriptMarkdown.formatTime(context.date.timeIntervalSince(startedAt)))
                    .font(.system(size: 28, weight: .medium, design: .monospaced))
                    .foregroundStyle(Theme.muted)
            }
            Text("Recording continues if you close this window.")
                .font(.system(size: 11))
                .foregroundStyle(Theme.muted2)
            Button("Stop and transcribe") {
                Task { await workflow.stopAndTranscribe() }
            }
            .buttonStyle(.borderedProminent)
            .tint(Theme.badgeRed)
            .controlSize(.large)
            .accessibilityIdentifier("conversation.stop-and-transcribe")
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func progressView(
        title: String,
        detail: String,
        fractionCompleted: Double? = nil,
        progressLabel: String? = nil
    ) -> some View {
        VStack(spacing: 16) {
            Spacer()
            if let fractionCompleted {
                ProgressView(value: fractionCompleted)
                    .progressViewStyle(.linear)
                    .frame(width: 300)
                Text(progressLabel ?? "\(Int((fractionCompleted * 100).rounded()))%")
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Theme.muted)
            } else {
                ProgressView().controlSize(.large)
            }
            Text(title)
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Theme.ink)
            Text(detail)
                .font(.system(size: 12))
                .foregroundStyle(Theme.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 480)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder
    private var reviewView: some View {
        if let draft = workflow.draft {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        speakerEditor(draft)
                        if !draft.usedSpeakerDiarization {
                            Label(
                                draft.speakerSeparationFallback?.reviewMessage
                                    ?? "Automatic speaker separation was unavailable. Add speakers and assign rows manually.",
                                systemImage: "person.2.slash"
                            )
                            .font(.system(size: 11))
                            .foregroundStyle(Theme.muted)
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 9))
                        }
                        transcriptEditor(draft)
                    }
                    .padding(22)
                }
                Divider()
                reviewFooter
            }
        }
    }

    private func speakerEditor(_ draft: ConversationTranscriptDraft) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Speakers")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Theme.ink)
                Spacer()
                Button("Add speaker", action: workflow.addSpeaker)
                    .buttonStyle(.borderless)
                    .font(.system(size: 11, weight: .semibold))
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 10)], spacing: 10) {
                ForEach(draft.orderedSpeakerIDs, id: \.self) { speakerID in
                    HStack(spacing: 8) {
                        Image(systemName: "person.crop.circle.fill")
                            .foregroundStyle(Theme.green)
                        TextField(
                            "Speaker name",
                            text: Binding(
                                get: { workflow.draft?.speakerNames[speakerID] ?? "" },
                                set: { workflow.renameSpeaker(speakerID, to: $0) }
                            )
                        )
                        .textFieldStyle(.roundedBorder)
                        .accessibilityIdentifier("conversation.speaker-name.\(speakerID)")
                    }
                }
            }
        }
    }

    private func transcriptEditor(_ draft: ConversationTranscriptDraft) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Transcript")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Theme.ink)
            ForEach(draft.segments) { segment in
                VStack(alignment: .leading, spacing: 9) {
                    HStack {
                        Text(ConversationTranscriptMarkdown.formatTime(segment.startTime))
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(Theme.muted2)
                        Picker(
                            "Speaker",
                            selection: Binding(
                                get: { workflow.draft?.segments.first(where: { $0.id == segment.id })?.speakerID ?? segment.speakerID },
                                set: { workflow.assignSegment(segment.id, to: $0) }
                            )
                        ) {
                            ForEach(draft.orderedSpeakerIDs, id: \.self) { speakerID in
                                Text(draft.speakerNames[speakerID] ?? speakerID).tag(speakerID)
                            }
                        }
                        .labelsHidden()
                        .frame(width: 180)
                        Spacer()
                    }
                    TextEditor(
                        text: Binding(
                            get: { workflow.draft?.segments.first(where: { $0.id == segment.id })?.text ?? "" },
                            set: { workflow.updateSegmentText(segment.id, text: $0) }
                        )
                    )
                    .font(.system(size: 12))
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: 58)
                    .padding(7)
                    .background(Color.white, in: RoundedRectangle(cornerRadius: 7))
                    .overlay(RoundedRectangle(cornerRadius: 7).stroke(Theme.lineStrong))
                    .accessibilityIdentifier("conversation.segment-text.\(segment.id)")
                }
                .padding(12)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    private var reviewFooter: some View {
        VStack(spacing: 8) {
            if let uploadError = workflow.uploadError {
                Text(uploadError)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Theme.badgeRed)
            }
            HStack {
                Button("Discard", role: .destructive, action: discardConversation)
                Button("Save Markdown…", action: saveMarkdown)
                Spacer()
                Button("Attach to Team Room") {
                    Task {
                        await workflow.attach { content, threadID, attachment, idempotencyKey in
                            await appState.sendMessage(
                                content,
                                to: threadID,
                                idempotencyKey: idempotencyKey,
                                uploads: [
                                    MessageUpload(
                                        name: attachment.filename,
                                        mimeType: ConversationTranscriptAttachment.mimeType,
                                        data: attachment.data
                                    )
                                ]
                            )
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(Theme.green)
                .accessibilityIdentifier("conversation.attach-transcript")
            }
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 14)
        .background(Theme.surface)
    }

    private func attachedView(filename: String) -> some View {
        VStack(spacing: 18) {
            Spacer()
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 54))
                .foregroundStyle(Theme.green)
            Text("Transcript attached")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Theme.ink)
            Text(filename)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(Theme.muted)
            HStack {
                Button("Done", action: close).buttonStyle(.bordered)
                Button("Record another") {
                    workflow.discard()
                }
                .buttonStyle(.borderedProminent)
                .tint(Theme.green)
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func failureView(message: String) -> some View {
        VStack(spacing: 16) {
            Spacer()
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 38))
                .foregroundStyle(.orange)
            Text("Conversation transcript stopped")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Theme.ink)
            Text(message)
                .font(.system(size: 12))
                .foregroundStyle(Theme.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 500)
            HStack {
                Button("Discard", role: .destructive, action: discardConversation)
                if workflow.canRetryTranscription {
                    Button("Retry local transcription") {
                        Task { await workflow.retryTranscription() }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Theme.green)
                }
            }
            if workflow.canRetryTranscription {
                Text("The source recording remains available until you discard this conversation or quit Rooms.")
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.muted2)
            }
            Spacer()
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func saveMarkdown() {
        guard let attachment = workflow.markdownAttachment() else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = attachment.filename
        panel.allowedContentTypes = [UTType(filenameExtension: "md") ?? .plainText]
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try workflow.saveMarkdown(to: url)
            appState.showToast("Markdown transcript saved")
        } catch {
            appState.showToast("Could not save the Markdown transcript")
        }
    }

    private func discardConversation() {
        workflow.discard()
    }
}
