#!/usr/bin/env bash
#
# MacNetLedger Uninstaller for macOS
# Unloads launchd service, removes binaries, and optionally cleans up database.
#

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
   echo "Error: This uninstaller must be run with sudo privileges."
   echo "Usage: sudo ./scripts/uninstall.sh [--purge-data]"
   exit 1
fi

echo "=========================================================="
echo "          Uninstalling MacNetLedger for macOS             "
echo "=========================================================="

PLIST_TARGET="/Library/LaunchDaemons/dev.zenmi.macnetledgerd.plist"
BIN_TARGET="/usr/local/bin/macnetledgerd"
APP_SUPPORT_DIR="/Library/Application Support/MacNetLedger"

# 1. Unload and remove launchd plist
if [[ -f "${PLIST_TARGET}" ]]; then
    echo "[1/3] Stopping and unloading launchd service..."
    launchctl unload "${PLIST_TARGET}" 2>/dev/null || true
    rm -f "${PLIST_TARGET}"
fi

# 2. Remove daemon binary
if [[ -f "${BIN_TARGET}" ]]; then
    echo "[2/3] Removing daemon binary: ${BIN_TARGET}"
    rm -f "${BIN_TARGET}"
fi

# 3. Handle data directory
PURGE_DATA=false
if [[ "${1:-}" == "--purge-data" ]]; then
    PURGE_DATA=true
fi

if [[ "${PURGE_DATA}" == true ]]; then
    echo "[3/3] Purging telemetry database and logs..."
    rm -rf "${APP_SUPPORT_DIR}"
    rm -f /var/log/macnetledgerd.log /var/log/macnetledgerd.error.log
else
    echo "[3/3] Preserving historical ledger at ${APP_SUPPORT_DIR}"
    echo "      (Pass --purge-data if you wish to completely wipe the SQLite database)."
fi

echo "=========================================================="
echo " ✓ MacNetLedger daemon uninstalled successfully.          "
echo "=========================================================="
