import AppKit
import SwiftUI

/// Native menu-bar interaction: left-click toggles the tray; right-click opens
/// a conventional context menu. `MenuBarExtra` cannot support both gestures.
@MainActor
final class StatusItemController: NSObject {
    private let appState: AppState
    private let overlayController = EventOverlayController()
    private var statusItem: NSStatusItem?
    private var popover: NSPopover?
    private var pinnedWindow: NSWindow?
    private var settingsWindow: NSWindow?
    private var contextMenu: NSMenu?
    private var observationTask: Task<Void, Never>?

    init(appState: AppState) {
        self.appState = appState
        super.init()
    }

    func install() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = item.button {
            button.imagePosition = .imageLeft
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
            button.action = #selector(statusItemClicked(_:))
            button.target = self
            button.toolTip = "Rooms"
        }
        statusItem = item

        let popover = NSPopover()
        popover.contentSize = NSSize(width: Theme.trayWidth, height: Theme.trayHeight)
        popover.behavior = .transient
        popover.animates = true
        popover.delegate = self
        self.popover = popover
        reloadPopoverContent()

        let menu = NSMenu()
        addMenuItem("Open Rooms", action: #selector(openFromMenu(_:)), to: menu)
        addMenuItem("Settings…", action: #selector(openSettings(_:)), to: menu)
        menu.addItem(.separator())
        addMenuItem("Quit Rooms", action: #selector(quit(_:)), keyEquivalent: "q", to: menu)
        contextMenu = menu

        appState.onNewEvent = { [weak self] event in
            guard let self, self.appState.overlayEnabled else { return }
            self.overlayController.show(
                event: event,
                autoDismiss: self.appState.overlayAutoDismiss,
                duration: self.appState.overlayDuration
            )
        }
        overlayController.onOpen = { [weak self] event in
            guard let self else { return }
            self.appState.prepareActivityOverlay(event)
            self.showPopover()
        }

        refreshButton()
        startObservingState()
    }

    func teardown() {
        observationTask?.cancel()
        observationTask = nil
        appState.onNewEvent = nil
        overlayController.dismissAll()
        closePopover()
        pinnedWindow?.orderOut(nil)
        settingsWindow?.orderOut(nil)
        if let item = statusItem {
            NSStatusBar.system.removeStatusItem(item)
        }
        statusItem = nil
        popover = nil
        pinnedWindow = nil
        settingsWindow = nil
        contextMenu = nil
    }

    private func addMenuItem(
        _ title: String,
        action: Selector,
        keyEquivalent: String = "",
        to menu: NSMenu
    ) {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: keyEquivalent)
        item.target = self
        menu.addItem(item)
    }

    @objc private func statusItemClicked(_ sender: Any?) {
        guard NSApp.currentEvent?.type == .rightMouseUp else {
            togglePopover()
            return
        }
        showContextMenu()
    }

    @objc private func openFromMenu(_ sender: Any?) {
        showPopover()
    }

    @objc private func openSettings(_ sender: Any?) {
        showSettingsWindow()
    }

    @objc private func quit(_ sender: Any?) {
        NSApp.terminate(nil)
    }

    private func showContextMenu() {
        guard let button = statusItem?.button, let menu = contextMenu else { return }
        closePopover()
        menu.popUp(
            positioning: nil,
            at: NSPoint(x: 0, y: button.bounds.height + 2),
            in: button
        )
    }

    private func togglePopover() {
        popover?.isShown == true ? closePopover() : showPopover()
    }

    private func showPopover() {
        guard let button = statusItem?.button, let popover else { return }
        if appState.selectedTab == .chat { appState.markSelectedThreadRead() }
        reloadPopoverContent()
        NSApp.activate(ignoringOtherApps: true)
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        button.highlight(true)
    }

    private func closePopover() {
        popover?.performClose(nil)
        statusItem?.button?.highlight(false)
    }

    private func reloadPopoverContent() {
        guard let popover else { return }
        let root = TrayView()
            .environment(appState)
            .environment(\.trayChrome, popoverChrome())
        popover.contentViewController = NSHostingController(rootView: root)
    }

    private func popoverChrome() -> TrayChrome {
        TrayChrome(
            close: { [weak self] in self?.closePopover() },
            openPinned: { [weak self] in self?.showPinnedWindow() },
            openSettings: { [weak self] in self?.showSettingsWindow() }
        )
    }

    private func showPinnedWindow() {
        closePopover()
        if appState.selectedTab == .chat { appState.markSelectedThreadRead() }
        if pinnedWindow == nil {
            let root = TrayView(isPinned: true)
                .environment(appState)
                .environment(\.trayChrome, pinnedChrome())
            let hosting = NSHostingController(rootView: root)
            let window = NSPanel(
                contentRect: NSRect(
                    x: 0, y: 0,
                    width: Theme.trayWidth, height: Theme.trayHeight
                ),
                styleMask: [.titled, .closable, .fullSizeContentView, .nonactivatingPanel],
                backing: .buffered,
                defer: false
            )
            window.title = "Rooms"
            window.titleVisibility = .hidden
            window.titlebarAppearsTransparent = true
            window.isFloatingPanel = true
            window.level = .floating
            window.hidesOnDeactivate = false
            window.isReleasedWhenClosed = false
            window.contentViewController = hosting
            window.setContentSize(NSSize(width: Theme.trayWidth, height: Theme.trayHeight))
            window.center()
            pinnedWindow = window
        }
        pinnedWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func pinnedChrome() -> TrayChrome {
        TrayChrome(
            close: { [weak self] in self?.pinnedWindow?.orderOut(nil) },
            openPinned: { [weak self] in self?.showPinnedWindow() },
            openSettings: { [weak self] in self?.showSettingsWindow() }
        )
    }

    func showSettingsWindow() {
        closePopover()
        if settingsWindow == nil {
            let root = SettingsView().environment(appState)
            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 460, height: 340),
                styleMask: [.titled, .closable],
                backing: .buffered,
                defer: false
            )
            window.title = "Rooms Settings"
            window.isReleasedWhenClosed = false
            window.contentViewController = NSHostingController(rootView: root)
            window.center()
            settingsWindow = window
        }
        settingsWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func startObservingState() {
        observationTask?.cancel()
        observationTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                self.refreshButton()
                if !self.appState.overlayEnabled {
                    self.overlayController.dismissAll()
                }
                await withCheckedContinuation {
                    (continuation: CheckedContinuation<Void, Never>) in
                    withObservationTracking {
                        _ = self.appState.isSignedIn
                        _ = self.appState.totalUnreadCount
                        _ = self.appState.overlayEnabled
                    } onChange: {
                        continuation.resume()
                    }
                }
            }
        }
    }

    private func refreshButton() {
        guard let button = statusItem?.button else { return }
        let image = NSImage(named: "RoomsMark")
        image?.isTemplate = true
        image?.accessibilityDescription = "Rooms"
        button.image = image
        button.title = appState.isSignedIn && appState.totalUnreadCount > 0
            ? " \(appState.totalUnreadCount)"
            : ""
    }
}

extension StatusItemController: NSPopoverDelegate {
    nonisolated func popoverDidClose(_ notification: Notification) {
        Task { @MainActor in
            self.statusItem?.button?.highlight(false)
        }
    }
}

/// Host actions injected into tray content whether it lives in an NSPopover or
/// a pinned NSPanel; SwiftUI's dismiss/openWindow actions are scene-specific.
struct TrayChrome: Sendable {
    var close: @MainActor @Sendable () -> Void = {}
    var openPinned: @MainActor @Sendable () -> Void = {}
    var openSettings: @MainActor @Sendable () -> Void = {}
}

private enum TrayChromeKey: EnvironmentKey {
    static let defaultValue = TrayChrome()
}

extension EnvironmentValues {
    var trayChrome: TrayChrome {
        get { self[TrayChromeKey.self] }
        set { self[TrayChromeKey.self] = newValue }
    }
}
