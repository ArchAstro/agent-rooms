import SwiftUI

@main
struct RoomsApp: App {
    @State private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .task { await appState.restoreSession() }
        }
        .defaultSize(width: 1000, height: 680)
        .commands {
            SidebarCommands()
            RoomsCommands(appState: appState)
        }

        Settings {
            SettingsView()
                .environment(appState)
        }
    }
}

/// App-level menu commands.
struct RoomsCommands: Commands {
    let appState: AppState

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("New Room") {
                // Room creation lands with the rooms feature; the menu item
                // exists so the shell exercises command wiring end-to-end.
            }
            .keyboardShortcut("n", modifiers: [.command])
            .disabled(!appState.isSignedIn)
        }

        CommandGroup(after: .appSettings) {
            Divider()
            if appState.isSignedIn {
                Button("Sign Out") {
                    Task { await appState.signOut() }
                }
            }
        }
    }
}
