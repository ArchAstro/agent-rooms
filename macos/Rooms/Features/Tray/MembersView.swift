import SwiftUI

struct MembersView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Members").font(.system(size: 17, weight: .bold)).foregroundStyle(Theme.ink)
                    Text("\(agentCount) agents · \(appState.currentMembers.count - agentCount) people")
                        .font(.system(size: 10)).foregroundStyle(Theme.muted)
                }
                Spacer()
                Button("Add") { appState.openInFullApp("Add member") }
                    .buttonStyle(.plain).font(.system(size: 10, weight: .bold)).foregroundStyle(.white)
                    .padding(.horizontal, 10).padding(.vertical, 6).background(Theme.ink, in: RoundedRectangle(cornerRadius: 7))
            }.padding(15)

            ScrollView {
                VStack(spacing: 0) {
                    ForEach(appState.currentMembers) { member in
                        HStack(spacing: 10) {
                            ZStack(alignment: .bottomTrailing) {
                                Text(member.initials).font(.system(size: 9, weight: .bold)).foregroundStyle(.white)
                                    .frame(width: 30, height: 30).background(Theme.green, in: RoundedRectangle(cornerRadius: 9))
                                Circle().fill(member.presence == .active ? Theme.green : Theme.muted2)
                                    .frame(width: 7, height: 7).overlay(Circle().stroke(Theme.paper, lineWidth: 2))
                            }
                            VStack(alignment: .leading, spacing: 2) {
                                HStack(spacing: 5) {
                                    Text(member.name).font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.ink)
                                    StatusPill(text: member.kind.rawValue, color: member.kind == .agent ? Theme.green : Theme.blue, background: member.kind == .agent ? Theme.greenSoft : Theme.blue.opacity(0.1))
                                }
                                Text("\(member.organization) · joined \(member.joined)")
                                    .font(.system(size: 9)).foregroundStyle(Theme.muted)
                            }
                            Spacer()
                            Text(member.role).font(.system(size: 9, weight: .semibold)).foregroundStyle(Theme.muted2)
                        }
                        .padding(.vertical, 10)
                        .overlay(alignment: .bottom) { Rectangle().fill(Theme.line).frame(height: 1) }
                    }
                }.padding(.horizontal, 15)
            }.scrollIndicators(.hidden)
        }
    }

    private var agentCount: Int { appState.currentMembers.filter { $0.kind == .agent }.count }
}
