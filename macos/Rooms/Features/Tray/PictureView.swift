import SwiftUI

/// The Picture — the distilled room state: greeting, digest, live view,
/// decisions, and the ask composer. Mirrors `#view-picture` in the mock.
struct PictureView: View {
    @Environment(AppState.self) private var appState
    @State private var draft = ""
    @FocusState private var askFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 9) {
                        morningNote
                            .padding(.bottom, 4)
                            .id("picture-top")

                        SectionLabel(text: "The picture")
                            .padding(.bottom, 2)

                        if let answer = appState.askAnswer {
                            answerCard(question: answer.question, text: answer.answer)
                                .transition(.move(edge: .top).combined(with: .opacity))
                        }

                        digestCard
                        liveViewCard
                        decisionCard
                    }
                    .padding(.horizontal, 14)
                    .padding(.top, 14)
                    .padding(.bottom, 10)
                }
                .scrollIndicators(.hidden)
                .animation(.easeOut(duration: 0.26), value: appState.askAnswer?.question)
                .onChange(of: appState.askAnswer?.question) {
                    withAnimation(.easeOut(duration: 0.3)) {
                        proxy.scrollTo("picture-top", anchor: .top)
                    }
                }
            }

            composer
        }
    }

    private var morningNote: some View {
        HStack(alignment: .top, spacing: 10) {
            Text("☀")
                .font(.system(size: 15))
                .frame(width: 29, height: 29)
                .background(Color(hex: 0xFFF3D6), in: RoundedRectangle(cornerRadius: 9))
            VStack(alignment: .leading, spacing: 2) {
                Text(appState.selectedRoom.greeting)
                    .font(.system(size: 16, weight: .bold))
                    .kerning(-0.3)
                    .foregroundStyle(Theme.ink)
                Text("\(appState.selectedRoom.stats) · \(attentionText)")
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.muted)
            }
        }
    }

    private var attentionText: String {
        appState.inboxCount > 0 ? "\(appState.inboxCount) need you" : "you're caught up"
    }

    private func answerCard(question: String, text: String) -> some View {
        SummaryCardView(
            kind: KindChip(text: "Answer", color: Theme.purple, background: Theme.purpleSoft),
            time: "just now",
            title: question,
            provenance: "Grounded in the room stream and inbox",
            actionTitle: "Open inbox",
            action: { appState.selectedTab = .inbox }
        ) {
            Text(text)
                .font(.system(size: 11))
                .lineSpacing(2.5)
                .foregroundStyle(Theme.ink2)
        }
    }

    private var digestCard: some View {
        SummaryCardView(
            kind: KindChip(text: "Digest", color: Theme.purple, background: Theme.purpleSoft),
            time: "refreshed 2m ago",
            title: appState.selectedRoom.digestTitle,
            provenance: "Fleet · 42 posts across 18 sessions",
            actionTitle: "See sources",
            action: { appState.selectedTab = .stream }
        ) {
            VStack(alignment: .leading, spacing: 5) {
                Text(appState.selectedRoom.digestText)
                Text(appState.selectedRoom.digestCaution)
            }
            .font(.system(size: 11))
            .lineSpacing(2.5)
            .foregroundStyle(Theme.ink2)
        }
    }

    private var liveViewCard: some View {
        SummaryCardView(
            kind: KindChip(text: "Live view", color: Theme.green, background: Theme.greenSoft),
            time: "now",
            title: "Who's working on what",
            provenance: "Live session exhaust · not a PR count",
            actionTitle: appState.liveViewPinned ? "Standing ✓" : "Keep standing",
            action: { appState.toggleLiveViewPinned() }
        ) {
            VStack(spacing: 7) {
                ForEach(TrayPlaceholders.people) { person in
                    HStack(spacing: 8) {
                        Text(person.initials)
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(.white)
                            .frame(width: 27, height: 27)
                            .background(person.avatarColor, in: RoundedRectangle(cornerRadius: 8))
                        VStack(alignment: .leading, spacing: 1) {
                            Text(person.name)
                                .font(.system(size: 10, weight: .bold))
                                .foregroundStyle(Theme.ink)
                            Text(person.work)
                                .font(.system(size: 10))
                                .foregroundStyle(Theme.muted)
                                .lineLimit(1)
                        }
                        Spacer(minLength: 6)
                        StatusPill(
                            text: person.status,
                            color: person.statusKind.color,
                            background: person.statusKind.background
                        )
                    }
                }
            }
        }
    }

    private var decisionCard: some View {
        let decision = TrayPlaceholders.decision
        return SummaryCardView(
            kind: KindChip(text: "Decision", color: Theme.amber, background: Theme.amberSoft),
            time: decision.time,
            title: decision.title,
            provenance: decision.provenance,
            actionTitle: "Open thread",
            action: { appState.openInFullApp("Open thread") }
        ) {
            Text(decision.body)
                .font(.system(size: 11))
                .lineSpacing(2.5)
                .foregroundStyle(Theme.ink2)
        }
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 7) {
                Text("✦")
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.purple)
                TextField("Ask this room…", text: $draft)
                    .textFieldStyle(.plain)
                    .font(.system(size: 11))
                    .focused($askFocused)
                    .onSubmit(submitAsk)
                Text("⌘↵")
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(Theme.muted2)
                Button(action: submitAsk) {
                    Image(systemName: "arrow.right")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(width: 24, height: 24)
                        .background(Theme.ink, in: RoundedRectangle(cornerRadius: 6))
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .padding(.vertical, 6)
            .padding(.leading, 10)
            .padding(.trailing, 7)
            .background(Color.white.opacity(0.92), in: RoundedRectangle(cornerRadius: 10))
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(askFocused ? Theme.purple.opacity(0.45) : Theme.lineStrong, lineWidth: 1)
            )

            Text("Ask for status, decisions, owners, or a summary. Answers keep their sources.")
                .font(.system(size: 9))
                .foregroundStyle(Theme.muted2)
                .padding(.horizontal, 2)
        }
        .padding(.top, 9)
        .padding(.horizontal, 12)
        .padding(.bottom, 12)
        .background(Color(hex: 0xF7F5F1).opacity(0.86))
        .overlay(alignment: .top) {
            Rectangle().fill(Theme.line).frame(height: 1)
        }
    }

    private func submitAsk() {
        let question = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty else { return }
        appState.ask(question)
        draft = ""
    }
}

/// Shared card chrome — mirrors `.summary-card`.
struct SummaryCardView<Content: View>: View {
    let kind: KindChip
    let time: String
    let title: String
    let provenance: String
    let actionTitle: String
    let action: () -> Void
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
                kind
                Spacer()
                Text(time)
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.muted2)
            }
            Text(title)
                .font(.system(size: 13, weight: .bold))
                .kerning(-0.15)
                .lineSpacing(2)
                .foregroundStyle(Theme.ink)
            content
            HStack(spacing: 7) {
                Text(provenance)
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.muted2)
                    .lineLimit(1)
                Spacer()
                Button(action: action) {
                    Text(actionTitle)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Theme.muted)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .contentShape(RoundedRectangle(cornerRadius: 6))
                }
                .buttonStyle(.plain)
                .hoverHighlight(cornerRadius: 6, color: Theme.surface)
            }
            .padding(.top, 3)
            .overlay(alignment: .top) {
                Rectangle().fill(Theme.line).frame(height: 1).offset(y: -1)
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.8), in: RoundedRectangle(cornerRadius: 13))
        .overlay(
            RoundedRectangle(cornerRadius: 13)
                .stroke(Color(hex: 0x37332D).opacity(0.1), lineWidth: 1)
        )
    }
}
