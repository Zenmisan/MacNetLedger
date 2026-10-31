# MacNetLedger (`dev.zenmi.macnetledger`)

**System-Wide Process Lineage Bandwidth Ledger & Mobile Hotspot Guardian for macOS Monterey (12.7+) & Modern macOS**

MacNetLedger is a free, high-signal, persistent network telemetry and hotspot monitoring application engineered natively for macOS. It resolves the limitations of proprietary tools (such as session-reset upon lid close, lack of history, and paywalled quotas) by pairing an ultra-lightweight Darwin `launchd` collector daemon with a sleek menu bar status pill and inspector flyout.

---

## The Problem It Solves

Unlike mobile operating systems, macOS treats Wi-Fi connections as unmetered by default. When tethered to a mobile phone hotspot, stealth system daemons (`nsurlsessiond`, `cloudd`, `photolibraryd`, `softwareupdated`) and browser helper processes consume gigabytes of cellular data in the background without user consent.

Existing proprietary tools (e.g. TripMode) have severe constraints in their free or trial states:
1. **Lid-Close Session Wipes**: Closing your MacBook lid or entering sleep tears down sockets, zeroing out ephemeral monitors and restarting tracking from 0 MB.
2. **No Historical Records**: Past usage is inaccessible across days, weeks, or billing cycles.
3. **High Resource Overhead**: Bulky background agents drain battery life on older machines like the MacBook Air (2013).

**MacNetLedger solves all three**:
* **Perpetual Persistence**: Telemetry is committed atomically to SQLite in WAL mode every 2 seconds. When your laptop goes to sleep, restarts, or closes its lid, **zero data is lost**.
* **Dual-Tier Historical Rollups**: Granular 5-minute buckets are preserved for 14 days, and 1-hour rollups are retained for 400+ days.
* **Hotspot-Aware Accounting**: Automatically detects connection type (Personal Hotspot vs. Home Wi-Fi) and tags all traffic accordingly.
* **Ultra-Lightweight**: Built on Darwin's native `/usr/bin/nettop` and POSIX primitives—consumes `< 0.5% CPU` and `< 25MB RAM`, ideal for older Intel Haswell hardware as well as Apple Silicon.

---

## Architectural Overview

```
┌────────────────────────────────────────────────────────┐
│                   macOS Menu Bar                       │
│    [ ↓ 1.4 MB/s ↑ 82 KB/s ·  nsurlsessiond ]         │
└──────────────────────────┬─────────────────────────────┘
                           │ User Click
┌──────────────────────────▼─────────────────────────────┐
│          Flyout Inspector Panel (540px)               │
│  - Live Rates & Peak Window Indicator                  │
│  - Network Filter: [ All | Hotspot Only | Wi-Fi ]     │
│  - Time Range Presets: [ LIVE | 24H | 7D | 30D ]       │
│  - Interactive 32-Bar Sparkline Histogram              │
│  - Proportional Dual-Color Bars (Cyan Down / Amber Up) │
│  - Collapsible Process Lineage Tree (.app bundles)     │
│  - Hotspot Daily Budget Warning Gauge                  │
└──────────────────────────┬─────────────────────────────┘
                           │ Read-Only WAL Query (< 3ms)
┌──────────────────────────▼─────────────────────────────┐
│   SQLite Database: /Library/Application Support/       │
│               MacNetLedger/ledger.db                   │
└──────────────────────────▲─────────────────────────────┘
                           │ 2s Periodic WAL Commit
┌──────────────────────────┴─────────────────────────────┐
│          Privileged Collector: macnetledgerd           │
│        (Managed by launchd as System Daemon)           │
├────────────────────────────────────────────────────────┤
│  1. /usr/bin/nettop -P -d -s 2 -L 0 (Darwin Kernel)   │
│  2. libproc (proc_pidpath) -> .app Bundle Lineage      │
│  3. CoreWLAN / airport -> Hotspot & SSID Tagger        │
│  4. Dual-Tier Time-Series Rollup Engine (5min / 1hour) │
└────────────────────────────────────────────────────────┘
```

---

## Key Features

- **Upward Process Lineage Attribution**:
  Under Darwin/macOS, helper processes (`Google Chrome Helper (Renderer)`, `Safari Networking`, `curl`, `git`) are automatically mapped up to their parent `.app` bundles (`Google Chrome.app`, `Safari.app`) or classified under human-friendly labels (`System: iCloud Sync`, `System: Background Downloads`).
- **Mobile Hotspot Guard**:
  Monitors active Wi-Fi SSID, BSSID, and network cost metrics. When connected to your phone's hotspot, MacNetLedger tags entries with `is_hotspot = 1` and tracks consumption against your daily cellular data ceiling.
- **Strict Privilege Separation**:
  - **Backend (`macnetledgerd`)**: Runs under `launchd` as root to capture all system-wide traffic (including privileged Apple services).
  - **Frontend UI (`MacNetLedger.app`)**: Runs purely in user space with zero root privileges, querying `ledger.db` with `PRAGMA query_only = ON;`.
- **Hallmark & UI/UX Pro Max Design Principles**:
  - High-contrast, dark mode interface adhering to WCAG AAA standards.
  - Distinct color tokens: **Cyan (`#22d3ee`)** for Download and **Amber (`#f59e0b`)** for Upload.
  - Native typography using Apple San Francisco Pro and San Francisco Mono tabular figures (eliminates layout shift).
  - 8-state interactive elements with smooth transitions.

---

## Directory Structure

```
MacNetLedger/
├── .agents/                          # Ralph's Method Track Management
│   ├── tracks.md                     # Master track ledger
│   └── tracks/
│       └── init_macnetledger_20261031/
│           ├── spec.md               # Technical specifications
│           └── plan.md               # Implementation plan & checklist
├── daemon/
│   ├── macnetledgerd.py              # Telemetry collector daemon
│   └── dev.zenmi.macnetledgerd.plist # launchd daemon service descriptor
├── app/                              # Menu bar user interface
│   ├── MacNetLedger/                 # Native Swift/SwiftUI application
│   │   ├── AppDelegate.swift         # NSStatusItem controller
│   │   ├── Views/                    # Menu pill & inspector views
│   │   └── Models/                   # SQLite query & data structures
├── scripts/
│   ├── install.sh                    # Setup daemon & directory permissions (sudo)
│   ├── uninstall.sh                  # Clean daemon and database teardown (sudo)
│   └── build_app.sh                  # Builds native MacNetLedger.app via swiftc
├── tests/
│   ├── test_lineage.py               # Process lineage unit tests
│   ├── test_nettop_parser.py         # nettop CSV stream parser tests
│   └── test_storage.py               # SQLite rollup and schema tests
├── Makefile                          # Build and testing targets
└── README.md                         # Project documentation
```

---

## Installation & Quickstart (macOS 12.7+)

### Option A: 1-Click GUI Installer (.pkg)
For users who do not want to touch terminal or build from source:
1. Download **`MacNetLedger-Installer.pkg`** from the [GitHub Releases](https://github.com/Zenmisan/MacNetLedger/releases).
2. Double-click the installer and follow the standard macOS setup wizard.
3. The installer automatically provisions the background daemon, registers `launchd`, installs the app to `/Applications`, and starts MacNetLedger in your Menu Bar.

---

### Option B: 1-Line Terminal Install (No Git Clone Required)
Open Terminal and run:
```bash
curl -fsSL https://raw.githubusercontent.com/Zenmisan/MacNetLedger/main/scripts/get.sh | bash
```

---

### Option C: Developer Manual Build from Source
Run the setup script with administrative privileges to install the daemon and configure `launchd`:
```bash
chmod +x scripts/*.sh
sudo ./scripts/install.sh
```

The installer will:
1. Provision `/Library/Application Support/MacNetLedger/` with `0777` directory permissions (allowing unprivileged UI access to SQLite WAL).
2. Install `macnetledgerd` into `/usr/local/bin/macnetledgerd`.
3. Register and start the `launchd` service at `/Library/LaunchDaemons/dev.zenmi.macnetledgerd.plist`.

### 2. Verify Daemon Status
Verify that `launchd` is running the collector:
```bash
sudo launchctl list | grep dev.zenmi.macnetledgerd
```

Inspect current live rates directly from the SQLite ledger:
```bash
sqlite3 -header -column "/Library/Application Support/MacNetLedger/ledger.db" "SELECT * FROM live_summary;"
```

### 3. Build & Launch the Menu Bar App
Compile the native Swift menu bar application using `swiftc` (no heavy Xcode IDE required):
```bash
./scripts/build_app.sh
```

Optionally move it to `/Applications/` and open it:
```bash
cp -r build/MacNetLedger.app /Applications/
open /Applications/MacNetLedger.app
```

---

## Uninstallation

To remove the background daemon and clean up:
```bash
# Keep database:
sudo ./scripts/uninstall.sh

# Or completely purge database & logs:
sudo ./scripts/uninstall.sh --purge-data
```

---

## Testing

Run the automated test suite locally:
```bash
make test
```

---

## License

Free and accessible for all Mac users. Built with pride for macOS Monterey and beyond.
