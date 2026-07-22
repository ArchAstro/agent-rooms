import SwiftUI

/// Needs-you inbox — request cards with a colored edge per kind and an
/// all-clear state. Mirrors `#view-inbox` in the mock.
struct InboxView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .bottom) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Needs you")
                        .font(.system(size: 17, weight: .bold))
                        .kerning(-0.4)
                        .foregroundStyle(Theme.ink)
                    Text(subtitle)
                        .font(.system(size: 10))
                        .foregroundStyle(Theme.muted)
                }
                Spacer()
                if !appState.requests.isEmpty {
                    Button {
                        appState.clearInbox()
                    } label: {
                        Text("Clear all")
                            .font(.system(size: 9))
                            .foregroundStyle(Theme.muted)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 4)
                            .contentShape(RoundedRectangle(cornerRadius: 6))
                    }
                    .buttonStyle(.plain)
                    .hoverHighlight(cornerRadius: 6, color: Theme.surface)
                }
            }
            .padding(.horizontal, 15)
            .padding(.top, 14)
            .padding(.bottom, 9)

            if appState.requests.isEmpty {
                emptyState
            } else {
                ScrollView {
                    VStack(spacing: 8) {
                        ForEach(appState.requests) { request in
                            RequestCardView(request: request)
                        }
                    }
                    .padding(.horizontal, 13)
                    .padding(.bottom, 14)
                }
                .scrollIndicators(.hidden)
            }
        }
    }

    private var subtitle: String {
        let count = appState.requests.count
        if count == 0 { return "Nothing waiting on you" }
        return "\(count) request\(count == 1 ? "" : "s") from the room"
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Text("✓")
                .font(.system(size: 20))
                .foregroundStyle(Theme.green)
                .frame(width: 38, height: 38)
                .background(Theme.greenSoft, in: RoundedRectangle(cornerRadius: 12))
            VStack(spacing: 4) {
                Text("You're caught up")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                Text("The room will bring the next consequential request here.")
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.muted)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(25)
    }
}

struct RequestCardView: View {
    @Environment(AppState.self) private var appState
    let request: InboxRequest

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                Text(request.kind.label)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(request.kind.color)
                Text(request.source)
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.muted2)
                Spacer()
                Text(request.time)
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.muted2)
            }

            Text(request.title)
                .font(.system(size: 11, weight: .semibold))
                .lineSpacing(2.5)
                .foregroundStyle(Theme.ink)
                .padding(.top, 7)
                .padding(.bottom, 4)

            Text(request.body)
                .font(.system(size: 10))
                .lineSpacing(2)
                .foregroundStyle(Theme.muted)

            HStack(spacing: 6) {
                actionButton(request.primaryAction, primary: true) {
                    withAnimation(.easeOut(duration: 0.25)) {
                        appState.resolveRequest(request, feedback: primaryFeedback)
                    }
                }
                actionButton(request.secondaryAction, primary: false) {
                    secondaryAction()
                }
            }
            .padding(.top, 9)
        }
        .padding(.top, 11)
        .padding(.bottom, 10)
        .padding(.leading, 13)
        .padding(.trailing, 11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white.opacity(0.82), in: RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Theme.line, lineWidth: 1)
        )
        .overlay(alignment: .leading) {
            UnevenRoundedRectangle(
                topLeadingRadius: 12, bottomLeadingRadius: 12,
                bottomTrailingRadius: 0, topTrailingRadius: 0
            )
            .fill(request.kind.color)
            .frame(width: 3)
        }
        .transition(.asymmetric(
            insertion: .opacity,
            removal: .move(edge: .trailing).combined(with: .opacity)
        ))
    }

    /// Mock-parity feedback per request kind (Approved / Handoff accepted /
    /// Marked seen).
    private var primaryFeedback: String {
        switch request.kind {
        case .approval: "Approved"
        case .handoff: "Handoff accepted"
        case .notice: "Marked seen"
        }
    }

    private func secondaryAction() {
        switch request.kind {
        case .approval:
            withAnimation(.easeOut(duration: 0.25)) {
                appState.resolveRequest(request, feedback: "Held for review")
            }
        case .handoff:
            appState.deferRequest(request)
        case .notice:
            appState.openInFullApp(request.secondaryAction)
        }
    }

    private func actionButton(
        _ title: String,
        primary: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(primary ? .white : Theme.ink2)
                .padding(.horizontal, 9)
                .padding(.vertical, 5)
                .background(
                    primary ? Theme.ink : Color.white,
                    in: RoundedRectangle(cornerRadius: 7)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 7)
                        .stroke(primary ? Theme.ink : Theme.lineStrong, lineWidth: 1)
                )
                .contentShape(RoundedRectangle(cornerRadius: 7))
        }
        .buttonStyle(.plain)
        .hoverHighlight(cornerRadius: 7, color: primary ? .white.opacity(0.12) : Theme.surface)
    }
}
