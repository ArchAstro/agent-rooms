import SwiftUI

/// Rooms lives in the menu bar. AppKit owns the status item so left-click can
/// open the tray while right-click provides the native Open / Settings / Quit
/// menu that `MenuBarExtra` cannot express.
@main
struct RoomsApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        // Accessory apps still need a Scene. User-facing windows are hosted by
        // StatusItemController so the popover and pinned panel share one state.
        Settings {
            EmptyView()
        }
        .commands {
            CommandGroup(replacing: .appSettings) {
                Button("Settings…") {
                    appDelegate.showSettings()
                }
                .keyboardShortcut(",", modifiers: .command)
            }
        }
    }
}
