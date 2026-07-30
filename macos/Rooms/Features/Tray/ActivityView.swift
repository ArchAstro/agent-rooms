import SwiftUI

struct ActivityView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        @Bindable var appState = appState
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Activity").font(.system(size: 17, weight: .bold)).foregroundStyle(Theme.ink)
                    Text("Network-scoped agent and thread events").font(.system(size: 9)).foregroundStyle(Theme.muted)
                }
                Spacer()
                Button {
                    appState.activityPaused.toggle()
                } label: {
                    Label(appState.activityPaused ? "Resume" : "Pause", systemImage: appState.activityPaused ? "play.fill" : "pause.fill")
                        .font(.system(size: 9, weight: .semibold)).foregroundStyle(appState.activityPaused ? Theme.green : Theme.muted)
                }.buttonStyle(.plain)
            }.padding(.horizontal, 14).padding(.vertical, 11)

            ScrollView(.horizontal) {
                HStack(spacing: 5) {
                    ForEach(StreamEvent.Level.allCases) { level in
                        Button { appState.activityFilter = level } label: {
                            Text(level.rawValue).font(.system(size: 9, weight: .semibold))
                                .foregroundStyle(appState.activityFilter == level ? Theme.ink : Theme.muted)
                                .padding(.horizontal, 8).padding(.vertical, 4)
                                .background(appState.activityFilter == level ? Color.white : .clear, in: Capsule())
                                .overlay(Capsule().stroke(appState.activityFilter == level ? Theme.lineStrong : .clear, lineWidth: 1))
                        }.buttonStyle(.plain)
                    }
                }.padding(.horizontal, 14)
            }.scrollIndicators(.hidden).padding(.bottom, 7)

            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(filteredEvents) { event in
                        HStack(alignment: .top, spacing: 9) {
                            Image(systemName: event.level.systemImage)
                                .font(.system(size: 10)).foregroundStyle(event.level.color)
                                .frame(width: 23, height: 23).background(event.level.background, in: RoundedRectangle(cornerRadius: 7))
                            VStack(alignment: .leading, spacing: 3) {
                                HStack {
                                    Text(event.author).font(.system(size: 10, weight: .bold)).foregroundStyle(Theme.ink)
                                    if appState.newEventIDs.contains(event.id) {
                                        Text("NEW").font(.system(size: 7, weight: .heavy)).foregroundStyle(Theme.green)
                                    }
                                    Spacer()
                                    Text(event.time).font(.system(size: 8)).foregroundStyle(Theme.muted2)
                                }
                                Text(event.body).font(.system(size: 10)).lineSpacing(2).foregroundStyle(Theme.ink2)
                                Button(event.sessionID) {
                                    appState.openInFullApp(
                                        "Activity session",
                                        extraQueryItems: [URLQueryItem(name: "session", value: event.sessionID)]
                                    )
                                }
                                    .buttonStyle(.plain).font(.system(size: 8, design: .monospaced)).foregroundStyle(Theme.muted2)
                            }
                        }
                        .padding(.vertical, 10)
                        .overlay(alignment: .bottom) { Rectangle().fill(Theme.line).frame(height: 1) }
                    }
                }.padding(.horizontal, 14)
            }.scrollIndicators(.hidden)
        }
    }

    private var filteredEvents: [StreamEvent] {
        appState.currentEvents.filter { $0.matches(appState.activityFilter) }
    }
}
