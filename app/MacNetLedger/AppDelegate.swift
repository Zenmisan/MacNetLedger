import Cocoa
import SwiftUI

@main
class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var popover: NSPopover!
    private var timer: Timer?
    private let reader = LedgerReader()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Create NSStatusItem in the macOS menu bar
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

        if let button = statusItem.button {
            button.title = "↓ 0 B/s  ↑ 0 B/s"
            button.action = #selector(togglePopover)
            button.target = self
        }

        // Initialize NSPopover with SwiftUI FlyoutPanelView
        popover = NSPopover()
        popover.contentSize = NSSize(width: 540, height: 640)
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(rootView: FlyoutPanelView(reader: reader))

        // Start 2-second UI poll timer
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.updateMenuBarPill()
        }
    }

    private func updateMenuBarPill() {
        guard let summary = reader.fetchLiveSummary(), let button = statusItem.button else { return }

        let downStr = formatRate(summary.rxRate)
        let upStr = formatRate(summary.txRate)

        if (summary.rxRate + summary.txRate) > 102400 && !summary.topProcess.isEmpty {
            // High throughput hog badge
            button.title = "↓ \(downStr) ↑ \(upStr) · \(summary.topProcess)"
        } else {
            button.title = "↓ \(downStr) ↑ \(upStr)"
        }
    }

    private func formatRate(_ bytesPerSec: Double) -> String {
        if bytesPerSec >= 1048576 {
            return String(format: "%.1f MB/s", bytesPerSec / 1048576)
        } else if bytesPerSec >= 1024 {
            return String(format: "%.0f KB/s", bytesPerSec / 1024)
        } else {
            return String(format: "%.0f B/s", bytesPerSec)
        }
    }

    @objc private func togglePopover() {
        guard let button = statusItem.button else { return }
        if popover.isShown {
            popover.performClose(nil)
        } else {
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }
}
