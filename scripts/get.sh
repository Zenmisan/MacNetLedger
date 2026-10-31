#!/usr/bin/env bash
#
# MacNetLedger 1-Line Installer for macOS
# Usage: curl -fsSL https://raw.githubusercontent.com/Zenmisan/MacNetLedger/main/scripts/get.sh | bash
#

set -euo pipefail

echo "=========================================================="
echo "          Downloading & Installing MacNetLedger           "
echo "=========================================================="

REPO_URL="https://github.com/Zenmisan/MacNetLedger.git"
TEMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

echo "Cloning latest release..."
git clone --depth 1 "${REPO_URL}" "${TEMP_DIR}/MacNetLedger"

cd "${TEMP_DIR}/MacNetLedger"

# Install daemon
echo "Installing daemon (requires administrator password)..."
sudo ./scripts/install.sh

# Build app
echo "Building native Menu Bar application..."
./scripts/build_app.sh

# Move to Applications
echo "Installing MacNetLedger into /Applications..."
cp -r build/MacNetLedger.app /Applications/

# Launch app
echo "Launching MacNetLedger in the macOS Menu Bar..."
open /Applications/MacNetLedger.app

echo "=========================================================="
echo " ✓ MacNetLedger is now running in your macOS Menu Bar!   "
echo "=========================================================="
