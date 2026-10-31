#!/usr/bin/env bash
#
# Builds MacNetLedger.app from Swift sources using swiftc on macOS
# Generates Universal 2 Binary (x86_64 for Intel MacBook Air 2013 + arm64 for Apple Silicon)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/../app/MacNetLedger"
BUILD_DIR="${SCRIPT_DIR}/../build"
APP_BUNDLE="${BUILD_DIR}/MacNetLedger.app"

echo "Building MacNetLedger.app..."
mkdir -p "${BUILD_DIR}/bin"
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
    <string>1.0.7</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
EOF

SWIFT_SOURCES=(
    "${APP_DIR}/LedgerReader.swift"
    "${APP_DIR}/Views/FlyoutPanel.swift"
    "${APP_DIR}/AppDelegate.swift"
    "${APP_DIR}/main.swift"
)

if command -v swiftc &>/dev/null; then
    SDK_FLAG=()
    if command -v xcrun &>/dev/null; then
        SDK_PATH="$(xcrun --show-sdk-path 2>/dev/null || true)"
        if [[ -n "${SDK_PATH}" ]]; then
            SDK_FLAG=(-sdk "${SDK_PATH}")
        fi
    fi

    # Build Intel x86_64 (MacBook Air 2013 Monterey)
    echo "Compiling for x86_64 (Intel)..."
    swiftc -O "${SDK_FLAG[@]}" \
        -target x86_64-apple-macos12.0 \
        -framework Cocoa \
        -framework SwiftUI \
        -lsqlite3 \
        "${SWIFT_SOURCES[@]}" \
        -o "${BUILD_DIR}/bin/MacNetLedger-x86_64" || true

    # Build Apple Silicon arm64
    echo "Compiling for arm64 (Apple Silicon)..."
    swiftc -O "${SDK_FLAG[@]}" \
        -target arm64-apple-macos12.0 \
        -framework Cocoa \
        -framework SwiftUI \
        -lsqlite3 \
        "${SWIFT_SOURCES[@]}" \
        -o "${BUILD_DIR}/bin/MacNetLedger-arm64" || true

    # Create Universal Binary if both exist
    if [[ -f "${BUILD_DIR}/bin/MacNetLedger-x86_64" ]] && [[ -f "${BUILD_DIR}/bin/MacNetLedger-arm64" ]] && command -v lipo &>/dev/null; then
        echo "Creating Universal Binary via lipo..."
        lipo -create -output "${APP_BUNDLE}/Contents/MacOS/MacNetLedger" \
            "${BUILD_DIR}/bin/MacNetLedger-x86_64" \
            "${BUILD_DIR}/bin/MacNetLedger-arm64"
    elif [[ -f "${BUILD_DIR}/bin/MacNetLedger-x86_64" ]]; then
        cp "${BUILD_DIR}/bin/MacNetLedger-x86_64" "${APP_BUNDLE}/Contents/MacOS/MacNetLedger"
    elif [[ -f "${BUILD_DIR}/bin/MacNetLedger-arm64" ]]; then
        cp "${BUILD_DIR}/bin/MacNetLedger-arm64" "${APP_BUNDLE}/Contents/MacOS/MacNetLedger"
    else
        # Direct native compile fallback
        swiftc -O "${SDK_FLAG[@]}" \
            -framework Cocoa \
            -framework SwiftUI \
            -lsqlite3 \
            "${SWIFT_SOURCES[@]}" \
            -o "${APP_BUNDLE}/Contents/MacOS/MacNetLedger"
    fi

    echo "✓ Built successfully: ${APP_BUNDLE}"
else
    echo "Note: swiftc is not present in the current environment (Linux)."
    echo "Run this script on macOS to compile the native MacNetLedger.app bundle."
fi
