import AppKit
import SwiftUI

/// A bounded stack of quiet, clickable room-event overlays. They stay above
/// normal windows, join every Space, and never steal keyboard focus.
@MainActor
final class EventOverlayController {
    var onOpen: ((StreamEvent) -> Void)?

    private var panels: [EventOverlayPanel] = []
    private let maxStack = 3

    func show(event: StreamEvent, autoDismiss: Bool, duration: TimeInterval) {
        let panel = EventOverlayPanel()
        let root = EventOverlayView(event: event) { [weak self, weak panel] in
            guard let self, let panel else { return }
            self.onOpen?(event)
            self.dismiss(panel)
        }
        let hosting = NSHostingView(rootView: root)
        hosting.frame = NSRect(x: 0, y: 0, width: 360, height: 116)
        panel.contentView = hosting
        panel.setContentSize(hosting.frame.size)

        for (index, existing) in panels.enumerated() {
            position(existing, index: index + 1)
        }
        panels.insert(panel, at: 0)
        position(panel, index: 0)
        panel.orderFrontRegardless()

        while panels.count > maxStack {
            panels.removeLast().orderOut(nil)
        }

        if autoDismiss {
            DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
                [weak self, weak panel] in
                guard let self, let panel,
                      self.panels.contains(where: { $0 === panel })
                else { return }
                self.dismiss(panel)
            }
        }
    }

    func dismissAll() {
        panels.forEach { $0.orderOut(nil) }
        panels.removeAll()
    }

    private func dismiss(_ panel: EventOverlayPanel) {
        panels.removeAll { $0 === panel }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.18
            panel.animator().alphaValue = 0
        } completionHandler: {
            Task { @MainActor [weak panel] in
                panel?.orderOut(nil)
            }
        }
        for (index, existing) in panels.enumerated() {
            position(existing, index: index)
        }
    }

    private func position(_ panel: NSPanel, index: Int) {
        guard let screen = NSScreen.main else { return }
        let visible = screen.visibleFrame
        let margin: CGFloat = 24
        let gap: CGFloat = 10
        let x = visible.maxX - panel.frame.width - margin
        let y = visible.maxY - panel.frame.height - margin
            - CGFloat(index) * (panel.frame.height + gap)
        panel.setFrameOrigin(NSPoint(x: x, y: y))
        panel.alphaValue = index == 0 ? 1 : 0.94
    }
}

final class EventOverlayPanel: NSPanel {
    init() {
        super.init(
            contentRect: NSRect(x: 0, y: 0, width: 360, height: 116),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        isFloatingPanel = true
        level = .statusBar
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        becomesKeyOnlyIfNeeded = true
        hidesOnDeactivate = false
    }

    override var canBecomeKey: Bool { true }
}
