import SwiftUI

struct ConnectionView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Organization connection")
                        .font(.system(size: 17, weight: .bold)).foregroundStyle(Theme.ink)
                    Text("The same host–collaborator relationship shown on the web.")
                        .font(.system(size: 10)).foregroundStyle(Theme.muted)
                }

                HStack(spacing: 8) {
                    organization(appState.selectedNetwork.hostOrganization, label: "HOST")
                    Image(systemName: "arrow.left.arrow.right")
                        .foregroundStyle(Theme.green)
                    organization(appState.selectedNetwork.collaboratorOrganization, label: "COLLABORATOR")
                }

                if let channel = appState.selectedNetwork.slackChannel {
                    HStack(spacing: 9) {
                        Image(systemName: "number.square.fill").foregroundStyle(Theme.green)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Slack channel").font(.system(size: 9, weight: .heavy)).foregroundStyle(Theme.muted2)
                            Text(channel).font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.ink)
                        }
                        Spacer()
                        Button("Manage") { appState.openInFullApp("Slack channel settings") }
                            .buttonStyle(.plain).font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.green)
                    }
                    .card()
                }

                SectionLabel(text: "Workstream")
                ForEach(appState.currentWorkstream) { item in
                    HStack(alignment: .top, spacing: 9) {
                        Image(systemName: item.kind == .thread ? "bubble.left.and.bubble.right" : "arrow.triangle.2.circlepath")
                            .font(.system(size: 11)).foregroundStyle(Theme.green).frame(width: 22, height: 22)
                            .background(Theme.greenSoft, in: RoundedRectangle(cornerRadius: 6))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title).font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.ink)
                            Text(item.detail).font(.system(size: 10)).foregroundStyle(Theme.muted)
                        }
                        Spacer()
                        Text(item.time).font(.system(size: 9)).foregroundStyle(Theme.muted2)
                    }
                    .padding(.vertical, 3)
                }
                Button("Open connection in web app") { appState.openInFullApp("Connection") }
                    .buttonStyle(.plain).font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.green)
            }
            .padding(15)
        }.scrollIndicators(.hidden)
    }

    private func organization(_ name: String, label: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.system(size: 8, weight: .heavy)).kerning(0.6).foregroundStyle(Theme.muted2)
            Text(name).font(.system(size: 12, weight: .bold)).foregroundStyle(Theme.ink).lineLimit(1)
            HStack(spacing: 4) {
                Circle().fill(Theme.green).frame(width: 5, height: 5)
                Text("Connected").font(.system(size: 9)).foregroundStyle(Theme.green)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading).card()
    }
}

private extension View {
    func card() -> some View {
        padding(11)
            .background(Color.white.opacity(0.8), in: RoundedRectangle(cornerRadius: 11))
            .overlay(RoundedRectangle(cornerRadius: 11).stroke(Theme.line, lineWidth: 1))
    }
}
