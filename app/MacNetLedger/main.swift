import Cocoa

// Standard entry point for AppKit applications without Nibs
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
