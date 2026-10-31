#!/usr/bin/env bash
#
# Builds a standalone macOS .pkg installer for MacNetLedger
# Uses native macOS `pkgbuild` (built into macOS, no extra tools required).
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}/.."
BUILD_DIR="${ROOT_DIR}/build"
PKG_ROOT="${BUILD_DIR}/pkg_root"
SCRIPTS_DIR="${BUILD_DIR}/pkg_scripts"
OUTPUT_PKG="${BUILD_DIR}/MacNetLedger-Installer.pkg"

echo "=========================================================="
echo "      Packaging MacNetLedger into 1-Click macOS .pkg      "
echo "=========================================================="

# 1. Ensure the app is built first
if [[ ! -d "${BUILD_DIR}/MacNetLedger.app" ]]; then
    echo "MacNetLedger.app not found. Building app first..."
    "${SCRIPT_DIR}/build_app.sh"
fi

# Clean previous packaging staging areas
rm -rf "${PKG_ROOT}" "${SCRIPTS_DIR}" "${OUTPUT_PKG}"
mkdir -p "${PKG_ROOT}/Applications"
mkdir -p "${PKG_ROOT}/usr/local/bin"
mkdir -p "${PKG_ROOT}/Library/LaunchDaemons"
mkdir -p "${PKG_ROOT}/Library/Application Support/MacNetLedger"
mkdir -p "${SCRIPTS_DIR}"

# 2. Stage files into root
echo "[1/3] Staging bundle payloads..."
cp -r "${BUILD_DIR}/MacNetLedger.app" "${PKG_ROOT}/Applications/"
cp "${ROOT_DIR}/daemon/macnetledgerd.py" "${PKG_ROOT}/usr/local/bin/macnetledgerd"
chmod +x "${PKG_ROOT}/usr/local/bin/macnetledgerd"
cp "${ROOT_DIR}/daemon/dev.zenmi.macnetledgerd.plist" "${PKG_ROOT}/Library/LaunchDaemons/"

# 3. Create postinstall script for pkgbuild
cat << 'EOF' > "${SCRIPTS_DIR}/postinstall"
#!/bin/bash
set -e

# Fix permissions
chmod 0755 /usr/local/bin/macnetledgerd
chown root:wheel /usr/local/bin/macnetledgerd
chmod 0644 /Library/LaunchDaemons/dev.zenmi.macnetledgerd.plist
chown root:wheel /Library/LaunchDaemons/dev.zenmi.macnetledgerd.plist
chmod 0777 "/Library/Application Support/MacNetLedger"

# Register and start launchd daemon
launchctl unload /Library/LaunchDaemons/dev.zenmi.macnetledgerd.plist 2>/dev/null || true
launchctl load -w /Library/LaunchDaemons/dev.zenmi.macnetledgerd.plist

# Terminate any old running instance so the newly updated binary starts
killall MacNetLedger 2>/dev/null || true
sleep 1

# Launch the menu bar app for the currently logged in GUI user
CURRENT_USER=$(stat -f "%Su" /dev/console)
if [ -n "$CURRENT_USER" ] && [ "$CURRENT_USER" != "root" ]; then
    sudo -u "$CURRENT_USER" open "/Applications/MacNetLedger.app" || true
fi

exit 0
EOF
chmod +x "${SCRIPTS_DIR}/postinstall"

# 4. Build .pkg package using pkgbuild
if command -v pkgbuild &>/dev/null; then
    echo "[2/3] Compiling native Apple .pkg installer..."
    pkgbuild \
        --root "${PKG_ROOT}" \
        --scripts "${SCRIPTS_DIR}" \
        --identifier "dev.zenmi.MacNetLedger" \
        --version "1.0.4" \
        --install-location "/" \
        "${OUTPUT_PKG}"
    echo "[3/3] Package generated successfully:"
    echo "      ${OUTPUT_PKG}"
else
    echo "Note: pkgbuild is a macOS utility. On macOS, this script generates a native .pkg."
fi
