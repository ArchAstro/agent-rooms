import AppKit
import UserNotifications

/// Owns the shared state and native menu-bar shell for the LSUIElement app.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private(set) var appState: AppState!
    private var statusItemController: StatusItemController!
    private var mentionNotifier: MentionNotifier?
    private var launchTask: Task<Void, Never>?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        if !Self.isRunningUnitTests {
            let notifier = MentionNotifier()
            mentionNotifier = notifier
            notifier.configure(delegate: self)
        }

        let state = AppState()
        appState = state
        state.onMention = { [weak self] mention in
            self?.mentionNotifier?.deliver(mention)
        }

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
        appState?.onMention = nil
        statusItemController?.teardown()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func showSettings() {
        statusItemController?.showSettingsWindow()
    }

    private static var isRunningUnitTests: Bool {
        ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
            || NSClassFromString("XCTestCase") != nil
    }
}

extension AppDelegate: UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler:
            @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        // `.list` keeps the mention in Notification Center after its banner
        // presentation. Rooms never removes delivered mention notifications.
        completionHandler([.banner, .list, .sound])
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let mention = MessageMention(
            userInfo: response.notification.request.content.userInfo
        )
        if response.actionIdentifier == UNNotificationDefaultActionIdentifier,
           let mention
        {
            Task { @MainActor [weak self] in
                self?.statusItemController.openMention(mention.target)
            }
        }
        completionHandler()
    }
}
