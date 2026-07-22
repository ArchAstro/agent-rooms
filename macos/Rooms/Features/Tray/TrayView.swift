import SwiftUI

/// The Team Room tray — the panel hosted by the menu bar item (and the
/// pinned "Keep visible" window). Head row, Picture/Inbox/Stream
/// segments, and the ask composer, per docs/mocks/team-room-menubar.html.
struct TrayView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openWindow) private var openWindow

    /// True when hosted in the pinned floating window instead of the
    /// menu-bar popover.
    var isPinned = false

    @State private var showingRoomSwitcher = false

    var body: some View {
        VStack(spacing: 0) {
            switch appState.phase {
            case .restoring:
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            case .signedOut, .signingIn:
                WelcomeTrayView()
            case .signedIn:
                header
                activeView
                    .animation(.easeOut(duration: 0.22), value: appState.selectedTab)
            }
        }
        .animation(.easeOut(duration: 0.2), value: appState.toast)
        .frame(width: Theme.trayWidth, height: Theme.trayHeight)
        .background(Theme.paper)
        .overlay(alignment: .bottom) { toastOverlay }
        .task {
            await appState.restoreSession()
            appState.startLiveFeed()
        }
    }

    @ViewBuilder
    private var toastOverlay: some View {
        if let toast = appState.toast {
            Text(toast)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color(hex: 0x201E1B).opacity(0.9), in: RoundedRectangle(cornerRadius: 9))
                .overlay(
                    RoundedRectangle(cornerRadius: 9)
                        .stroke(Color.white.opacity(0.13), lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.24), radius: 17, y: 6)
                .padding(.bottom, 74)
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .id(toast)
        }
    }

    private var header: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                roomButton
                HStack(spacing: 5) {
                    Circle()
                        .fill(Color(hex: 0x20A37F))
                        .frame(width: 5, height: 5)
                        .shadow(color: Color(hex: 0x20A37F).opacity(0.35), radius: 3)
                    Text("live")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Theme.green)
                }
                Spacer()
                iconButton(
                    systemImage: "pin",
                    title: isPinned ? "Back to the menu bar" : "Keep visible",
                    active: isPinned
                ) {
                    if isPinned {
                        dismiss()
                    } else {
                        openWindow(id: "rooms-panel")
                        dismiss()
                    }
                }
                if !isPinned {
                    iconButton(systemImage: "xmark", title: "Close tray") {
                        dismiss()
                    }
                }
            }
            .frame(height: 39)
            .padding(.horizontal, 15)

            segments
                .padding(.horizontal, 15)
                .padding(.bottom, 8)

            Rectangle()
                .fill(Theme.line)
                .frame(height: 1)
        }
        .padding(.top, isPinned ? 8 : 4)
    }

    private var roomButton: some View {
        Button {
            showingRoomSwitcher.toggle()
        } label: {
            HStack(spacing: 8) {
                Text(String(appState.selectedRoom.name.prefix(1)))
                    .font(.system(size: 12, weight: .heavy))
                    .foregroundStyle(.white)
                    .frame(width: 26, height: 26)
                    .background(
                        LinearGradient(
                            colors: [Color(hex: 0x282622), Color(hex: 0x5C5851)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        in: RoundedRectangle(cornerRadius: 8)
                    )
                Text(appState.selectedRoom.name)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Theme.ink)
                    .lineLimit(1)
                Image(systemName: "chevron.down")
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(Theme.muted2)
            }
            .padding(.vertical, 4)
            .padding(.leading, 3)
            .padding(.trailing, 6)
            .contentShape(RoundedRectangle(cornerRadius: 7))
        }
        .buttonStyle(.plain)
        .hoverHighlight()
        .popover(isPresented: $showingRoomSwitcher, arrowEdge: .bottom) {
            RoomSwitcherView(isPresented: $showingRoomSwitcher)
                .environment(appState)
        }
    }

    private var segments: some View {
        HStack(spacing: 2) {
            ForEach(Array(TrayTab.allCases.enumerated()), id: \.element) { index, tab in
                Button {
                    appState.selectedTab = tab
                } label: {
                    HStack(spacing: 3) {
                        Text(tab.rawValue)
                            .font(.system(size: 11, weight: .semibold))
                        if tab == .inbox && appState.inboxCount > 0 {
                            Text("\(appState.inboxCount)")
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(.white)
                                .padding(.horizontal, 5)
                                .padding(.vertical, 1)
                                .background(Theme.badgeRed, in: Capsule())
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
                    .foregroundStyle(appState.selectedTab == tab ? Theme.ink : Theme.muted)
                    .background(
                        appState.selectedTab == tab ? Color.white.opacity(0.9) : .clear,
                        in: RoundedRectangle(cornerRadius: 7)
                    )
                    .shadow(
                        color: appState.selectedTab == tab ? Color(hex: 0x1E1B17).opacity(0.1) : .clear,
                        radius: 1.5, y: 1
                    )
                    .contentShape(RoundedRectangle(cornerRadius: 7))
                }
                .buttonStyle(.plain)
                .hoverHighlight(color: appState.selectedTab == tab ? .clear : Color(hex: 0x21201C).opacity(0.045))
                .keyboardShortcut(KeyEquivalent(Character("\(index + 1)")), modifiers: .command)
                .help("\(tab.rawValue) (⌘\(index + 1))")
            }
        }
        .padding(.top, 4)
    }

    @ViewBuilder
    private var activeView: some View {
        switch appState.selectedTab {
        case .picture:
            PictureView()
        case .inbox:
            InboxView()
        case .stream:
            StreamView()
        }
    }

    private func iconButton(
        systemImage: String,
        title: String,
        active: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(active ? Theme.purple : Color(hex: 0x595650))
                .frame(width: 28, height: 28)
                .background(
                    active ? Theme.purpleSoft : .clear,
                    in: RoundedRectangle(cornerRadius: 7)
                )
                .contentShape(RoundedRectangle(cornerRadius: 7))
        }
        .buttonStyle(.plain)
        .hoverHighlight()
        .help(title)
    }
}

/// Room picker popover — mirrors `.channel-switcher`.
struct RoomSwitcherView: View {
    @Environment(AppState.self) private var appState
    @Binding var isPresented: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("ROOMS")
                .font(.system(size: 9, weight: .bold))
                .kerning(0.8)
                .foregroundStyle(Theme.muted2)
                .padding(.horizontal, 8)
                .padding(.top, 5)
                .padding(.bottom, 4)

            ForEach(appState.availableRooms) { room in
                Button {
                    appState.selectRoom(room)
                    isPresented = false
                } label: {
                    HStack(spacing: 9) {
                        Text("#")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(Color(hex: 0x716D66))
                            .frame(width: 21, height: 21)
                            .background(Color(hex: 0xE6E3DD), in: RoundedRectangle(cornerRadius: 6))
                        VStack(alignment: .leading, spacing: 1) {
                            Text(room.name)
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(Theme.ink)
                            Text(room.meta)
                                .font(.system(size: 10))
                                .foregroundStyle(Theme.muted2)
                        }
                        Spacer(minLength: 4)
                        if room.unreadCount > 0 {
                            Text("\(room.unreadCount)")
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(.white)
                                .padding(.horizontal, 5)
                                .padding(.vertical, 1)
                                .background(Theme.badgeRed, in: Capsule())
                        }
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 7)
                    .background(
                        room.id == appState.selectedRoom.id ? Color(hex: 0xECE9E3) : .clear,
                        in: RoundedRectangle(cornerRadius: 7)
                    )
                    .contentShape(RoundedRectangle(cornerRadius: 7))
                }
                .buttonStyle(.plain)
                .hoverHighlight(color: Theme.surface)
            }

            // Identity — membership decides what each member can ask.
            if let email = appState.userEmail {
                Rectangle()
                    .fill(Theme.line)
                    .frame(height: 1)
                    .padding(.vertical, 5)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Signed in as \(email)")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Theme.ink2)
                        .lineLimit(1)
                    Text("Membership decides what you can ask.")
                        .font(.system(size: 9))
                        .foregroundStyle(Theme.muted2)
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 5)
            }
        }
        .padding(6)
        .frame(width: 236)
    }
}
