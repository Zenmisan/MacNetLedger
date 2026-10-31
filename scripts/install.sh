#!/usr/bin/env bash
#
# MacNetLedger Installer for macOS Monterey (12.7+) and beyond
# Sets up /Library/Application Support/MacNetLedger, installs daemon, and registers launchd service.
#

set -euo pipefail

# Check for root / sudo privileges
if [[ $EUID -ne 0 ]]; then
   echo "Error: This installer must be run with sudo privileges."
   echo "Usage: sudo ./scripts/install.sh"
   exit 1
fi

echo "=========================================================="
echo "           Installing MacNetLedger for macOS              "
echo "=========================================================="

APP_SUPPORT_DIR="/Library/Application Support/MacNetLedger"
DAEMON_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/daemon"
BIN_TARGET="/usr/local/bin/macnetledgerd"
PLIST_TARGET="/Library/LaunchDaemons/dev.zenmi.macnetledgerd.plist"

# 1. Create Application Support Directory
echo "[1/4] Provisioning storage directory: ${APP_SUPPORT_DIR}"
mkdir -p "${APP_SUPPORT_DIR}"
chmod 0777 "${APP_SUPPORT_DIR}"

# 2. Install Daemon Binary
echo "[2/4] Installing daemon executable: ${BIN_TARGET}"
mkdir -p /usr/local/bin
cp "${DAEMON_SRC}/macnetledgerd.py" "${BIN_TARGET}"
chmod 0755 "${BIN_TARGET}"
chown root:wheel "${BIN_TARGET}"

# 3. Install Launchd Plist Descriptor
echo "[3/4] Installing launchd service descriptor: ${PLIST_TARGET}"
# Unload previous instance if active
if launchctl list | grep -q "dev.zenmi.macnetledgerd"; then
    echo "Unloading existing daemon instance..."
    launchctl unload "${PLIST_TARGET}" 2>/dev/null || true
fi

cp "${DAEMON_SRC}/dev.zenmi.macnetledgerd.plist" "${PLIST_TARGET}"
chown root:wheel "${PLIST_TARGET}"
chmod 0644 "${PLIST_TARGET}"

# 4. Load and Start Launchd Daemon
echo "[4/4] Activating and starting MacNetLedger daemon..."
launchctl load -w "${PLIST_TARGET}"

echo "=========================================================="
echo " ✓ MacNetLedger installation completed successfully!      "
echo "=========================================================="
echo "Daemon status:"
sleep 1
launchctl list | grep dev.zenmi.macnetledgerd || echo "Note: Check /var/log/macnetledgerd.log for initial boot status."
echo ""
echo "Ledger database located at:"
echo "  ${APP_SUPPORT_DIR}/ledger.db"
