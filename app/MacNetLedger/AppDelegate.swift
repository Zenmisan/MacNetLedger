import Cocoa
import SwiftUI

@main
class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var popover: NSPopover!
    private var fallbackWindow: NSWindow?
    private var timer: Timer?
    private let reader = LedgerReader()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Ensure accessory activation policy
        NSApp.setActivationPolicy(.accessory)

        // Create NSStatusItem in the macOS menu bar
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.autosaveName = "dev.zenmi.MacNetLedger.StatusItem"

        if let button = statusItem.button {
            if let icon = NSImage(systemSymbolName: "network", accessibilityDescription: "MacNetLedger") {
                icon.isTemplate = true
                button.image = icon
                button.imagePosition = .imageLeading
            }
            button.title = " 0 B/s"
            button.action = #selector(togglePopover)
            button.target = self
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        // Initialize NSPopover with SwiftUI FlyoutPanelView
        popover = NSPopover()
        popover.contentSize = NSSize(width: 540, height: 640)
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(rootView: FlyoutPanelView(reader: reader))

        // Initial pill update
        updateMenuBarPill()

        // Start 2-second UI poll timer
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.updateMenuBarPill()
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        togglePopover()
        return true
    }

    private func updateMenuBarPill() {
        guard let button = statusItem.button else { return }

        if let summary = reader.fetchLiveSummary() {
            let downStr = formatRate(summary.rxRate)
            let upStr = formatRate(summary.txRate)

            if (summary.rxRate + summary.txRate) > 102400 && !summary.topProcess.isEmpty {
                // High throughput hog badge
                button.title = " ↓ \(downStr) · \(summary.topProcess)"
            } else {
                button.title = " ↓ \(downStr) ↑ \(upStr)"
            }
        } else {
            // Waiting for daemon connection
            button.title = " ..."
        }
    }

    private func formatRate(_ bytesPerSec: Double) -> String {
        if bytesPerSec >= 1048576 {
            return String(format: "%.1fM", bytesPerSec / 1048576)
        } else if bytesPerSec >= 1024 {
            return String(format: "%.0fK", bytesPerSec / 1024)
        } else {
            return String(format: "%.0fB", bytesPerSec)
        }
    }

    @objc private func togglePopover() {
        let currentEvent = NSApp.currentEvent
        if currentEvent?.type == .rightMouseUp {
            showContextMenu()
            return
        }

        if let button = statusItem.button, button.window != nil {
            if popover.isShown {
                popover.performClose(nil)
            } else {
                popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
                popover.contentViewController?.view.window?.makeKey()
            }
        } else {
            // Fallback: If statusItem is not visible or clipped from menu bar, open standalone window
            toggleFallbackWindow()
        }
    }

    private func showContextMenu() {
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Open MacNetLedger", action: #selector(toggleFallbackWindow), keyEquivalent: "o"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil // Restore toggle behavior after click
    }

    @objc private func toggleFallbackWindow() {
        if let win = fallbackWindow, win.isVisible {
            win.orderOut(nil)
            return
        }
        if fallbackWindow == nil {
            let win = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 540, height: 640),
                styleMask: [.titled, .closable, .miniaturizable],
                backing: .buffered,
                defer: false
            )
            win.title = "MacNetLedger"
            win.isReleasedWhenClosed = false
            win.center()
            win.contentView = NSHostingView(rootView: FlyoutPanelView(reader: reader))
            fallbackWindow = win
        }
        fallbackWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
