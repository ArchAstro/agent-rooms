import SwiftUI

/// Compact native counterpart to the web network detail page.
struct TrayView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.trayChrome) private var trayChrome
    var isPinned = false
    @State private var showingNetworkSwitcher = false

    var body: some View {
        VStack(spacing: 0) {
            switch appState.phase {
            case .restoring:
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            case .signedOut, .signingIn:
                WelcomeTrayView()
            case .signedIn:
                header
                activeView
                    .animation(.easeOut(duration: 0.2), value: appState.selectedTab)
            }
        }
        .frame(width: Theme.trayWidth, height: Theme.trayHeight)
        .background(Theme.paper)
        .overlay(alignment: .bottom) { toastOverlay }
    }

    private var header: some View {
        VStack(spacing: 0) {
            HStack(spacing: 9) {
                Button { showingNetworkSwitcher.toggle() } label: {
                    HStack(spacing: 8) {
                        Text(String(appState.selectedNetwork.name.prefix(1)))
                            .font(.system(size: 12, weight: .heavy))
                            .foregroundStyle(.white)
                            .frame(width: 27, height: 27)
                            .background(Theme.green, in: RoundedRectangle(cornerRadius: 8))
                        VStack(alignment: .leading, spacing: 1) {
                            Text(appState.selectedNetwork.name)
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(Theme.ink)
                            Text("Active network")
                                .font(.system(size: 9))
                                .foregroundStyle(Theme.green)
                        }
                        Image(systemName: "chevron.down")
                            .font(.system(size: 8, weight: .bold))
                            .foregroundStyle(Theme.muted2)
                    }
                    .contentShape(RoundedRectangle(cornerRadius: 8))
                }
                .buttonStyle(.plain)
                .hoverHighlight()
                .popover(isPresented: $showingNetworkSwitcher, arrowEdge: .bottom) {
                    NetworkSwitcherView(isPresented: $showingNetworkSwitcher)
                        .environment(appState)
                }

                Spacer()
                chromeButton("arrow.up.right.square", help: "Open full web app") {
                    appState.openInFullApp(appState.selectedNetwork.name)
                }
                chromeButton("pin", help: isPinned ? "Back to menu bar" : "Keep visible", active: isPinned) {
                    isPinned ? trayChrome.close() : trayChrome.openPinned()
                }
                if !isPinned {
                    chromeButton("xmark", help: "Close") { trayChrome.close() }
                }
            }
            .frame(height: 43)
            .padding(.horizontal, 14)

            HStack(spacing: 2) {
                ForEach(Array(TrayTab.allCases.enumerated()), id: \.element) { index, tab in
                    Button {
                        appState.selectedTab = tab
                        if tab == .chat { appState.markSelectedThreadRead() }
                    } label: {
                        Text(tab.rawValue)
                            .font(.system(size: 10, weight: .semibold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 6)
                            .foregroundStyle(appState.selectedTab == tab ? Theme.ink : Theme.muted)
                            .background(appState.selectedTab == tab ? Color.white : .clear, in: RoundedRectangle(cornerRadius: 7))
                    }
                    .buttonStyle(.plain)
                    .keyboardShortcut(KeyEquivalent(Character("\(index + 1)")), modifiers: .command)
                }
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 8)

            Rectangle().fill(Theme.line).frame(height: 1)
        }
        .padding(.top, isPinned ? 8 : 4)
    }

    @ViewBuilder private var activeView: some View {
        switch appState.selectedTab {
        case .connection: ConnectionView()
        case .members: MembersView()
        case .chat: ChatView()
        case .activity: ActivityView()
        }
    }

    @ViewBuilder private var toastOverlay: some View {
        if let toast = appState.toast {
            Text(toast)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(Theme.ink.opacity(0.92), in: RoundedRectangle(cornerRadius: 9))
                .shadow(color: .black.opacity(0.2), radius: 14, y: 5)
                .padding(.bottom, 18)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    private func chromeButton(_ image: String, help: String, active: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: image)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(active ? Theme.green : Theme.muted)
                .frame(width: 28, height: 28)
                .background(active ? Theme.greenSoft : .clear, in: RoundedRectangle(cornerRadius: 7))
        }
        .buttonStyle(.plain).hoverHighlight().help(help)
    }
}

struct NetworkSwitcherView: View {
    @Environment(AppState.self) private var appState
    @Binding var isPresented: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("NETWORKS")
                .font(.system(size: 9, weight: .heavy))
                .kerning(0.8)
                .foregroundStyle(Theme.muted2)
                .padding(.horizontal, 9).padding(.top, 8).padding(.bottom, 4)
            ForEach(appState.availableNetworks) { network in
                Button {
                    appState.selectNetwork(network)
                    isPresented = false
                } label: {
                    HStack(spacing: 9) {
                        Text(String(network.name.prefix(1)))
                            .font(.system(size: 10, weight: .bold))
                            .foregroundStyle(.white)
                            .frame(width: 24, height: 24)
                            .background(Theme.green, in: RoundedRectangle(cornerRadius: 7))
                        VStack(alignment: .leading, spacing: 1) {
                            Text(network.name).font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.ink)
                            Text(network.relationship).font(.system(size: 9)).foregroundStyle(Theme.muted2)
                        }
                        Spacer()
                        let unreadCount = appState.unreadCount(for: network.id)
                        if unreadCount > 0 {
                            Text("\(unreadCount)")
                                .font(.system(size: 9, weight: .bold)).foregroundStyle(.white)
                                .padding(.horizontal, 5).padding(.vertical, 1)
                                .background(Theme.badgeRed, in: Capsule())
                        }
                    }
                    .padding(.horizontal, 9).padding(.vertical, 7)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain).hoverHighlight()
            }
        }
        .padding(5).frame(width: 285)
    }
}
