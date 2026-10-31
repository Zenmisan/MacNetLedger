# Implementation Plan: MacNetLedger Initialization

**Track ID**: `init_macnetledger_20261031`  
**Status**: COMPLETED  

---

## Tasks & Milestones

### Phase 1: Core Telemetry Daemon (`macnetledgerd`)
- [x] **Task 1.1: Database Schema & Migration**
  - Implemented SQLite initialization script with WAL mode, synchronous=NORMAL.
  - Tables: `live_state`, `live_summary`, `rollup_5min`, `rollup_1hour`, `hotspot_budget`.
- [x] **Task 1.2: Darwin Process Lineage Resolver**
  - Bound Darwin `proc_pidpath` via Python `ctypes`.
  - Implemented `.app` bundle parser and system daemon mapper.
  - Added in-memory LRU cache with TTL (5s) to eliminate redundant kernel calls.
- [x] **Task 1.3: Network State & Hotspot Detector**
  - Implemented active network probe (`airport -I` / `networksetup`).
  - Extracted SSID and tagged `is_hotspot` status.
- [x] **Task 1.4: NetTop Stream Collector Engine**
  - Wrapped `/usr/bin/nettop -P -d -s 2 -L 0 -J bytes_in,bytes_out,interface` with unbuffered pipe reader.
  - Parsed CSV deltas, computed rates, and buffered time-series entries.
- [x] **Task 1.5: Rollup Aggregation & Maintenance Worker**
  - Implemented 5-minute bucket flusher.
  - Implemented 1-hour rollup worker for older buckets.
  - Implemented retention pruning (14-day 5min, 400-day 1hour).

### Phase 2: System Integration & Launchd
- [x] **Task 2.1: LaunchDaemon Plist Creation**
  - Created `daemon/dev.zenmi.macnetledgerd.plist` targeting `/Library/LaunchDaemons/`.
  - Configured `KeepAlive = true`, `RunAtLoad = true`, and appropriate logging paths.
- [x] **Task 2.2: Automated Install & Permission Scripts**
  - Created `scripts/install.sh` for daemon deployment and database directory provisioning (`0777` dir, `0644` db).
  - Created `scripts/uninstall.sh` for clean removal.

### Phase 3: Menu Bar User Interface
- [x] **Task 3.1: Menu Bar Pill Component**
  - Status bar pill displaying live download (Cyan) & upload (Amber) rates in `AppDelegate.swift`.
  - Dynamic hog alert when throughput > 100 KB/s.
- [x] **Task 3.2: Flyout Inspector Panel**
  - Translucent 540px panel in `FlyoutPanel.swift`.
  - Active time range selector (`LIVE`, `24H`, `2D`, `7D`, `30D`).
  - Network selector (`All`, `Hotspot Only`, `Wi-Fi Only`).
  - Proportional dual-segment rate bars with expandable lineage tree.
  - Hotspot daily budget progress bar and alert trigger.
  - Build script in `scripts/build_app.sh`.

### Phase 4: Testing & Verification
- [x] **Task 4.1: Unit Test Suite**
  - Created `tests/test_lineage.py`, `tests/test_storage.py`, `tests/test_nettop_parser.py`.
  - 14 tests passing in 0.027s.
- [x] **Task 4.2: Hardware & Battery Profiling Guidelines**
  - Benchmarked parser and memory models.

---

## Verification Criteria
1. `macnetledgerd` stays under 0.8% CPU and < 25 MB RSS during continuous 2-second sampling.
2. Closing the MacBook Air lid and reopening it retains all previous telemetry in SQLite without resetting totals.
3. Network traffic generated while connected to a mobile hotspot is accurately tagged with `is_hotspot = 1`.
4. Read queries against `ledger.db` from the UI complete in < 3ms without database locking errors.
