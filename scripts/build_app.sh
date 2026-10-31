#!/usr/bin/env bash
#
# Builds MacNetLedger.app from Swift sources using swiftc on macOS
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/../app/MacNetLedger"
BUILD_DIR="${SCRIPT_DIR}/../build"
APP_BUNDLE="${BUILD_DIR}/MacNetLedger.app"

echo "Building MacNetLedger.app..."
mkdir -p "${BUILD_DIR}"
rm -rf "${APP_BUNDLE}"

# Create .app directory layout
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

# Generate Info.plist
cat << 'EOF' > "${APP_BUNDLE}/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>MacNetLedger</string>
    <key>CFBundleIdentifier</key>
    <string>dev.zenmi.MacNetLedger</string>
    <key>CFBundleName</key>
    <string>MacNetLedger</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF

if command -v swiftc &>/dev/null; then
    swiftc -O \
        -sdk "$(xcrun --show-sdk-path 2>/dev/null || echo '')" \
        -framework Cocoa \
        -framework SwiftUI \
        -lsqlite3 \
        "${APP_DIR}/LedgerReader.swift" \
        "${APP_DIR}/Views/FlyoutPanel.swift" \
        "${APP_DIR}/AppDelegate.swift" \
        -o "${APP_BUNDLE}/Contents/MacOS/MacNetLedger"
    echo "✓ Built successfully: ${APP_BUNDLE}"
else
    echo "Note: swiftc is not present in the current environment (Linux)."
    echo "Run this script on macOS to compile the native MacNetLedger.app bundle."
fi
