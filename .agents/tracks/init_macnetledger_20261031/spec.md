# Track Specification: MacNetLedger Initialization

**Track ID**: `init_macnetledger_20261031`  
**Date**: 2026-10-31  
**Target Environment**: macOS 12.7 Monterey (Intel x86_64 / MacBook Air 2013) & Apple Silicon (Universal)  
**Author**: Zenmi / Antigravity  

---

## 1. Problem Statement

On macOS, users tethered to metered mobile hotspots face severe, unmonitored data loss from background services (`nsurlsessiond`, `cloudd`, `softwareupdated`, `photolibraryd`, browser helpers).
Existing proprietary tools (e.g. TripMode) have prohibitive limitations:
1. **Lid-Close & Sleep Reset**: When the MacBook Air lid is closed, sockets suspend; proprietary session-only meters reset counters to zero.
2. **Locked / Non-Existent History**: No arbitrary historical inspection across days, weeks, or billing cycles without paid licenses.
3. **Black-box Closed Ecosystem**: No transparency on how network flows are tracked, heavy memory/CPU overhead, and paywalled quotas.

Existing open-source alternatives on macOS (Activity Monitor, LuLu, Wireshark) are either non-persistent firewalls or ephemeral system diagnostics that do not provide per-application lineage accounting, metered network tagging, or time-brush inspection.

---

## 2. Solution: MacNetLedger

MacNetLedger adapts the proven architecture of **NetLedger (Omarchy/Linux)** into a zero-compromise, lightweight native macOS network monitor.

### Key Tenets
1. **Zero External Kernel Extensions / NetworkExtension Entitlements**:
   - Leverages macOS native `/usr/bin/nettop` in non-interactive delta-logging mode (`-P -d -s 2 -L 0 -J bytes_in,bytes_out,interface`).
   - Runs under `launchd` as a root daemon (`dev.zenmi.macnetledgerd.plist`) to capture both user software and stealth Apple daemons.
2. **Persistent SQLite WAL Store Across Sleep / Wake**:
   - Telemetry written to `/Library/Application Support/MacNetLedger/ledger.db` with permissions `0644`.
   - Dual-tier time series: 5-minute buckets (retained for 14 days) and 1-hour rollups (retained for 400+ days).
   - Survives lid-close, sleep, user logouts, and full reboots without losing historical metrics.
3. **Upward Process Lineage on Darwin**:
   - Resolves executable paths via Darwin standard C `proc_pidpath` (`libproc`).
   - Automatically maps nested helpers (e.g. `Google Chrome Helper (Renderer)`) to top-level `.app` bundles (`Google Chrome.app`).
   - Categorizes system daemons with human-readable labels (`nsurlsessiond` -> "Apple Background Transfers").
4. **Network Context & Hotspot Tagging**:
   - Checks active Wi-Fi SSID and network path flags (`airport -I` / CoreWLAN / `scutil`).
   - Tags each telemetry bucket with `network_name` and `is_hotspot` (1/0), enabling granular mobile-data-only audits.
5. **High-Signal Native UI**:
   - Native macOS Menu Bar status item (`NSStatusItem`).
   - Minimal CPU footprint (< 0.5%) and RAM (< 25MB) suitable for 2013 MacBook Air hardware.
   - Preserves NetLedger's signature Cyan (Download) / Amber (Upload) proportional bars, time-brush sparklines, and top hog alerts.
