# MacNetLedger: Engineering & Implementation Plan

> Master engineering roadmap following **Ralph's Method** (`.agents/tracks/init_macnetledger_20261031/`).

---

## 1. System Architecture

```
                                  [ macOS Kernel ]
                                         │
                                  /usr/bin/nettop
                                         │ (CSV Stream)
                                         ▼
                             ┌───────────────────────┐
                             │    macnetledgerd      │
                             │  (launchd Root Daemon)│
                             └───────────┬───────────┘
                                         │
             ┌───────────────────────────┼───────────────────────────┐
             ▼                           ▼                           ▼
      [ libproc C API ]          [ CoreWLAN / SSID ]         [ SQLite WAL Engine ]
  (Bundle & Lineage Cache)     (Hotspot Detection Tag)     (Dual 5min & 1hr Rollup)
                                                                     │
                                                                     ▼
                                                         /Library/Application Support/
                                                            MacNetLedger/ledger.db
                                                                     │
                                                                     ▼ (Read-Only < 3ms)
                                                         ┌───────────────────────┐
                                                         │   MacNetLedger UI     │
                                                         │ (Native Menu Bar App) │
                                                         └───────────────────────┘
```

---

## 2. Work Breakdown Structure (WBS)

### Milestone 1: Core Telemetry Daemon (`macnetledgerd`)
* **Task 1.1: Database Schema & Migration**
  - Implement SQLite initialization script with WAL mode, `synchronous=NORMAL`.
  - Tables: `live_state`, `live_summary`, `rollup_5min`, `rollup_1hour`, `hotspot_budget`.
* **Task 1.2: Darwin Process Lineage Resolver**
  - Bind Darwin `proc_pidpath` via Python `ctypes`.
  - Implement `.app` bundle parser and system daemon mapper.
  - Implement an in-memory lineage cache with TTL (5 seconds) to minimize kernel calls.
* **Task 1.3: Network State & Hotspot Detector**
  - Query airport framework / `networksetup` / `scutil` for active SSID and interface.
  - Tag incoming metrics as `is_hotspot = 1` when connected to mobile hotspot.
* **Task 1.4: NetTop Stream Collector Engine**
  - Spawn `/usr/bin/nettop -P -d -s 2 -L 0 -J bytes_in,bytes_out,interface` with unbuffered pipe.
  - Parse CSV lines into structured `(pid, process_name, bytes_in, bytes_out, interface)` tuples.
* **Task 1.5: Aggregation & Rollup Engine**
  - Commit live state every 2 seconds to `live_state` and `live_summary`.
  - Aggregate 5-minute buckets into `rollup_5min`.
  - Maintenance thread: roll up 5-minute entries older than 1 hour into `rollup_1hour`.
  - Prune 5-minute records older than 14 days and 1-hour records older than 400 days.

### Milestone 2: launchd System Integration & Permissions
* **Task 2.1: LaunchDaemon Descriptor**
  - Create `/Library/LaunchDaemons/dev.zenmi.macnetledgerd.plist`.
  - Configure automatic start (`RunAtLoad`), respawn on crash (`KeepAlive`), and stdout/stderr logging.
* **Task 2.2: Automated Installer & Teardown**
  - `scripts/install.sh`: Creates application support directory (`/Library/Application Support/MacNetLedger/`), installs binary, sets permissions `0755` for directory and `0644` for SQLite database.
  - `scripts/uninstall.sh`: Safely unloads launchd daemon and cleans up files.

### Milestone 3: Native Menu Bar User Interface
* **Task 3.1: Status Bar Pill (`NSStatusItem`)**
  - Compact menu bar pill with live download & upload rates.
  - Dynamic bandwidth hog badge when rate > 100 KB/s.
* **Task 3.2: Flyout Inspector Panel (`NSPopover`)**
  - Translucent 540px panel (`NSVisualEffectView`).
  - Active time range selector (`LIVE`, `24H`, `2D`, `7D`, `30D`, `Custom`).
  - Network selector (`All`, `Hotspot Only`, `Wi-Fi Only`).
  - 32-bar interactive histogram with click-to-isolate scrubbing.
  - Dual-segment proportional process rows with collapsible lineage tree.
  - Hotspot daily budget progress bar and alert trigger.

### Milestone 4: Verification & Quality Assurance
* **Task 4.1: Automated Test Suite**
  - `test_lineage.py`: Verify bundle resolution and system daemon mapping.
  - `test_storage.py`: Verify SQLite WAL concurrent access, rollup aggregation, and retention pruning.
* **Task 4.2: Hardware & Battery Profiling**
  - Validate CPU usage remains under 0.8% on MacBook Air 2013 (Intel Core i5).
  - Verify zero data loss across lid close, sleep, and reboot.

---

## 3. Immediate Next Steps

1. Build the complete `macnetledgerd.py` collector daemon in `daemon/macnetledgerd.py`.
2. Generate the unit tests in `tests/`.
3. Create the `dev.zenmi.macnetledgerd.plist` launchd file and installer scripts in `scripts/`.
4. Build the user-facing Menu Bar interface.
