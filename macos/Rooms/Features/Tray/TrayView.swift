import SwiftUI

/// Compact native counterpart to the web network detail page.
struct TrayView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.trayChrome) private var trayChrome
    var isPinned = false
    @State private var showingNetworkSwitcher = false
    @State private var showingAccountMenu = false

    var body: some View {
        VStack(spacing: 0) {
            switch appState.phase {
            case .restoring:
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            case .signedOut, .signingIn:
                WelcomeTrayView()
            case .signedIn:
                header
                signedInContent
            }
        }
        .frame(width: Theme.trayWidth, height: Theme.trayHeight)
        .background(Theme.paper)
        .overlay(alignment: .bottom) { toastOverlay }
    }

    @ViewBuilder private var signedInContent: some View {
        if appState.isLoadingRooms && !appState.hasLoadedRooms {
            RoomLoadingView()
        } else if let error = appState.roomLoadError {
            RoomLoadFailureView(message: error)
        } else if appState.availableNetworks.isEmpty {
            EmptyRoomsView()
        } else {
            activeView
                .animation(.easeOut(duration: 0.2), value: appState.selectedTab)
        }
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
                            Text("Active Team Room")
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
                Button { showingAccountMenu.toggle() } label: {
                    Image(systemName: "gearshape.fill")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(showingAccountMenu ? Theme.green : Theme.muted)
                        .frame(width: 28, height: 28)
                        .background(
                            showingAccountMenu ? Theme.greenSoft : .clear,
                            in: RoundedRectangle(cornerRadius: 7)
                        )
                }
                .buttonStyle(.plain)
                .hoverHighlight()
                .help("Account and settings")
                .accessibilityLabel("Account and settings")
                .popover(isPresented: $showingAccountMenu, arrowEdge: .top) {
                    AccountMenuView(isPresented: $showingAccountMenu)
                        .environment(appState)
                        .environment(\.trayChrome, trayChrome)
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

private struct AccountMenuView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.trayChrome) private var trayChrome
    @Binding var isPresented: Bool
    @State private var isSigningOut = false
    @State private var showingSignOutConfirmation = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "person.crop.circle.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(Theme.green)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Signed in as")
                        .font(.system(size: 8, weight: .heavy))
                        .kerning(0.5)
                        .foregroundStyle(Theme.muted2)
                    Text(appState.accountDisplayName)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Theme.ink)
                        .lineLimit(1)
                    if let email = appState.accountEmail {
                        Text(email)
                            .font(.system(size: 9))
                            .foregroundStyle(Theme.muted)
                            .lineLimit(1)
                    }
                    if let organization = appState.accountOrganization {
                        Text(organization)
                            .font(.system(size: 9))
                            .foregroundStyle(Theme.muted)
                            .lineLimit(1)
                    }
                }
            }
            .padding(12)

            Rectangle().fill(Theme.line).frame(height: 1)

            Button {
                isPresented = false
                trayChrome.openSettings()
            } label: {
                Label("Settings…", systemImage: "gearshape")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .accountMenuButton()

            Button(role: .destructive) {
                showingSignOutConfirmation = true
            } label: {
                HStack {
                    Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
                    Spacer()
                    if isSigningOut {
                        ProgressView().controlSize(.small)
                    }
                }
                .contentShape(Rectangle())
            }
            .accountMenuButton(color: Theme.red)
            .disabled(isSigningOut)
        }
        .frame(width: 260)
        .padding(5)
        .confirmationDialog(
            "Sign out of Rooms?",
            isPresented: $showingSignOutConfirmation,
            titleVisibility: .visible
        ) {
            Button("Sign Out", role: .destructive) {
                performSignOut()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("You’ll need to sign in through ArchAgents again to open your Team Rooms.")
        }
    }

    private func performSignOut() {
        guard !isSigningOut else { return }
        isSigningOut = true
        Task {
            await appState.signOut()
            isSigningOut = false
            isPresented = false
        }
    }
}

private extension View {
    func accountMenuButton(color: Color = Theme.ink) -> some View {
        self
            .buttonStyle(.plain)
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 10)
            .padding(.vertical, 9)
            .hoverHighlight()
    }
}

struct NetworkSwitcherView: View {
    @Environment(AppState.self) private var appState
    @Binding var isPresented: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("TEAM ROOMS")
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

private struct RoomLoadingView: View {
    var body: some View {
        VStack(spacing: 12) {
            ProgressView()
            Text("Loading your Team Rooms…")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Theme.muted)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct RoomLoadFailureView: View {
    @Environment(AppState.self) private var appState
    let message: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 24))
                .foregroundStyle(Theme.amber)
            Text("Couldn’t load Team Rooms")
                .font(.system(size: 14, weight: .bold))
            Text(message)
                .font(.system(size: 10))
                .foregroundStyle(Theme.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 280)
            Button("Try Again") { Task { await appState.refreshRooms() } }
                .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct EmptyRoomsView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "person.3")
                .font(.system(size: 25))
                .foregroundStyle(Theme.green)
            Text("No Team Rooms yet")
                .font(.system(size: 14, weight: .bold))
            Text("Join or create a company Team Room in ArchAgents, then refresh.")
                .font(.system(size: 10))
                .foregroundStyle(Theme.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 270)
            Button("Refresh") { Task { await appState.refreshRooms() } }
                .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
