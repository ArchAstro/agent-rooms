import SwiftUI

/// Rooms lives in the menu bar: the tray panel drops from the status
/// item, and "Keep visible" moves it into a floating window — per
/// docs/mocks/team-room-menubar.html.
@main
struct RoomsApp: App {
    @State private var appState = AppState()

    var body: some Scene {
        MenuBarExtra {
            TrayView()
                .environment(appState)
        } label: {
            Image(systemName: "bubble.left.and.bubble.right.fill")
            if appState.isSignedIn && appState.inboxCount > 0 {
                Text("\(appState.inboxCount)")
            }
        }
        .menuBarExtraStyle(.window)

        // The pinned "Keep visible" panel.
        Window("Rooms", id: "rooms-panel") {
            TrayView(isPinned: true)
                .environment(appState)
        }
        .windowResizability(.contentSize)
        .defaultPosition(.topTrailing)

        Settings {
            SettingsView()
                .environment(appState)
        }
    }
}
