import Cocoa
import SwiftUI

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    public var statusItem: NSStatusItem!
    public var popover: NSPopover!
    public var mainWindow: NSWindow?
    private var timer: Timer?
    private let reader = LedgerReader()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 1. Create NSStatusItem in the macOS menu bar
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

        if let button = statusItem.button {
            if let icon = NSImage(systemSymbolName: "network", accessibilityDescription: "MacNetLedger") {
                icon.isTemplate = true
                button.image = icon
                button.imagePosition = .imageLeading
            }
            button.title = " 0 B/s"
            button.action = #selector(togglePopoverOrWindow)
            button.target = self
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        // 2. Initialize NSPopover with SwiftUI FlyoutPanelView
        popover = NSPopover()
        popover.contentSize = NSSize(width: 540, height: 640)
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(rootView: FlyoutPanelView(reader: reader))

        // 3. Immediately show the main window on first launch so user sees the interface
        showMainWindow()

        // 4. Update menu bar pill and start 1-second UI poll timer
        updateMenuBarPill()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.updateMenuBarPill()
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return true
    }

    @objc public func showMainWindow() {
        if mainWindow == nil {
            let win = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 540, height: 640),
                styleMask: [.titled, .closable, .miniaturizable],
                backing: .buffered,
                defer: false
            )
            win.title = "MacNetLedger"
            win.isReleasedWhenClosed = false
            win.delegate = self
            win.center()
            win.contentView = NSHostingView(rootView: FlyoutPanelView(reader: reader))
            mainWindow = win
        }
        mainWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func togglePopoverOrWindow() {
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
            showMainWindow()
        }
    }

    private func showContextMenu() {
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Open Window", action: #selector(showMainWindow), keyEquivalent: "o"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit MacNetLedger", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil
    }

    private func updateMenuBarPill() {
        guard let button = statusItem.button else { return }

        if let summary = reader.fetchLiveSummary() {
            let downStr = formatRate(summary.rxRate)
            let upStr = formatRate(summary.txRate)

            if (summary.rxRate + summary.txRate) > 102400 && !summary.topProcess.isEmpty {
                button.title = " ↓ \(downStr) · \(summary.topProcess)"
            } else {
                button.title = " ↓ \(downStr) ↑ \(upStr)"
            }
        } else {
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

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        // Hide window on close instead of destroying it
        sender.orderOut(nil)
        return false
    }
}
