import SwiftUI

/// The live stream — machine exhaust rendered as flat event rows with
/// filter pills. Mirrors `#view-stream` in the mock.
struct StreamView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        @Bindable var appState = appState
        VStack(spacing: 0) {
            HStack(spacing: 6) {
                Text("Live stream")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Theme.ink)
                Spacer()
                ForEach(StreamEvent.Filter.allCases) { filter in
                    Button {
                        appState.streamFilter = filter
                    } label: {
                        Text(filter.rawValue)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(
                                appState.streamFilter == filter ? Theme.ink : Theme.muted
                            )
                            .padding(.horizontal, 7)
                            .padding(.vertical, 3)
                            .background(
                                appState.streamFilter == filter
                                    ? Color(hex: 0xE7E4DE)
                                    : .clear,
                                in: Capsule()
                            )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 13)
            .padding(.top, 11)
            .padding(.bottom, 7)

            ScrollView {
                VStack(spacing: 0) {
                    ForEach(filteredEvents) { event in
                        EventRowView(event: event)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.bottom, 14)
                .padding(.top, 4)
            }
            .scrollIndicators(.hidden)
        }
    }

    private var filteredEvents: [StreamEvent] {
        appState.events.filter { $0.matches(appState.streamFilter) }
    }
}

struct EventRowView: View {
    let event: StreamEvent

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text(event.kind.glyph)
                .font(.system(size: 9, weight: .heavy))
                .foregroundStyle(event.kind.color)
                .frame(width: 20, height: 20)
                .background(event.kind.background, in: RoundedRectangle(cornerRadius: 6))

            VStack(alignment: .leading, spacing: 1) {
                Text(event.author)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(Theme.ink)
                Text(event.body)
                    .font(.system(size: 10))
                    .lineSpacing(2.5)
                    .foregroundStyle(Theme.ink2)
            }

            Spacer(minLength: 6)

            Text(event.time)
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(Theme.muted2)
        }
        .padding(.vertical, 8)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Theme.line).frame(height: 1)
        }
    }
}
