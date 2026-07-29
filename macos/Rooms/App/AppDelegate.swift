import AppKit

/// Owns the shared state and native menu-bar shell for the LSUIElement app.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private(set) var appState: AppState!
    private var statusItemController: StatusItemController!
    private var launchTask: Task<Void, Never>?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let state = AppState()
        appState = state

        let controller = StatusItemController(appState: state)
        statusItemController = controller
        controller.install()

        launchTask = Task {
            await state.restoreSession()
            guard !Task.isCancelled else { return }
            state.startLiveFeed()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        launchTask?.cancel()
        launchTask = nil
        appState?.stopLiveFeed()
        statusItemController?.teardown()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func showSettings() {
        statusItemController?.showSettingsWindow()
    }
}
