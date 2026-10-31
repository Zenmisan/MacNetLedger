#!/usr/bin/env python3
"""
MacNetLedger Daemon (macnetledgerd)
System-wide process lineage bandwidth ledger & mobile hotspot guardian for macOS Monterey (12.7+) and beyond.

Uses Darwin native nettop kernel diagnostics, libproc path attribution,
and dual-tier SQLite time-series rollups in WAL mode.
"""

import argparse
import ctypes
import datetime
import logging
import os
import re
import select
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("macnetledgerd")

# Default database location on macOS
DEFAULT_DB_PATH = "/Library/Application Support/MacNetLedger/ledger.db"

# Human-friendly mappings for known macOS system services
MACOS_SYSTEM_DAEMONS: Dict[str, Tuple[str, str, str]] = {
    # (Friendly Group Name, Category, Detail)
    "nsurlsessiond": ("Apple Background Transfers", "system", "iCloud, Music & App Store Downloads"),
    "cloudd": ("iCloud Drive Sync", "system", "iCloud Drive File Synchronization"),
    "bird": ("iCloud Documents", "system", "iCloud Desktop & Documents Daemon"),
    "photolibraryd": ("iCloud Photos Sync", "system", "Photos Library Cloud Sync"),
    "softwareupdated": ("macOS Software Update", "system", "OS Updates & Security Patches"),
    "mDNSResponder": ("Bonjour & System DNS", "system", "DNS Resolution & Local Discovery"),
    "apsd": ("Apple Push Notification", "system", "System Push Notifications Daemon"),
    "trustd": ("Apple Trust Evaluation", "system", "Certificate & TLS Validation"),
    "geod": ("Apple Location Services", "system", "CoreLocation Geo Daemon"),
    "AssetCacheLocatorService": ("Apple Content Caching", "system", "Local Network Caching Service"),
    "appstoreagent": ("Mac App Store Agent", "system", "App Store Background Downloads"),
    "commerce": ("Mac App Store Commerce", "system", "App Store Purchasing Subsystem"),
    "com.apple.WebKit.Networking": ("WebKit Web Engine", "system", "Safari & WebKit Networking Helper"),
    "Safari Networking": ("Safari Web Engine", "system", "Safari Network Process"),
    "identityservicesd": ("Apple Identity Services", "system", "iMessage & FaceTime Subsystem"),
    "akd": ("Apple Auth Kit", "system", "Apple ID Authentication Daemon"),
    "syncdefaultsd": ("iCloud Key-Value Sync", "system", "App Cloud Defaults Sync"),
    "CalendarAgent": ("Apple Calendar Sync", "system", "Calendar & Reminders Sync"),
    "accountsd": ("macOS Accounts Daemon", "system", "System Accounts & Credential Broker"),
    "findmydeviced": ("Apple Find My Daemon", "system", "Find My Mac Location Service"),
}

# Human-friendly CLI & Developer Tools mappings
MACOS_CLI_TOOLS: Dict[str, Tuple[str, str]] = {
    "curl": ("cURL", "cli"),
    "wget": ("wget", "cli"),
    "git": ("Git", "cli"),
    "git-remote-https": ("Git HTTPS Helper", "cli"),
    "ssh": ("SSH Client", "cli"),
    "rsync": ("rsync", "cli"),
    "brew": ("Homebrew", "dev"),
    "python": ("Python Runtime", "dev"),
    "python3": ("Python Runtime", "dev"),
    "node": ("Node.js Runtime", "dev"),
    "bun": ("Bun Runtime", "dev"),
    "deno": ("Deno Runtime", "dev"),
    "cargo": ("Rust Cargo", "dev"),
    "rustc": ("Rust Compiler", "dev"),
    "go": ("Go Toolchain", "dev"),
    "ruby": ("Ruby Runtime", "dev"),
    "docker": ("Docker Desktop", "dev"),
    "dockerd": ("Docker Daemon", "dev"),
}

# Lineage cache: pid -> (cache_time, (root_group, category, child_comm, child_detail))
LINEAGE_CACHE: Dict[int, Tuple[float, Tuple[str, str, str, str]]] = {}
CACHE_TTL_SEC = 5.0


class DarwinProcessResolver:
    """Resolves macOS Process PIDs to parent .app bundles or system daemons via libproc."""

    def __init__(self):
        self._libc = None
        self._proc_pidpath = None
        self._is_darwin = sys.platform == "darwin"

        if self._is_darwin:
            try:
                self._libc = ctypes.CDLL("libc.dylib")
                self._proc_pidpath = self._libc.proc_pidpath
                self._proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
                self._proc_pidpath.restype = ctypes.c_int
            except Exception as e:
                logger.warning("Could not initialize Darwin proc_pidpath: %s", e)

    def get_process_path(self, pid: int) -> Optional[str]:
        """Returns the absolute executable path for a given PID using proc_pidpath."""
        if not self._proc_pidpath or pid <= 0:
            return None
        buf = ctypes.create_string_buffer(4096)
        ret = self._proc_pidpath(pid, buf, 4096)
        if ret > 0:
            return buf.value.decode("utf-8", errors="replace")
        return None

    def resolve(self, pid: int, raw_comm: str) -> Tuple[str, str, str, str]:
        """
        Resolves (root_group, category, child_comm, child_detail).
        Uses caching to ensure ultra-low CPU overhead.
        """
        now = time.time()
        if pid in LINEAGE_CACHE:
            ts, cached = LINEAGE_CACHE[pid]
            if now - ts < CACHE_TTL_SEC:
                return cached

        # Check known system daemons by command name
        base_comm = raw_comm.split("/")[-1].strip()
        if base_comm in MACOS_SYSTEM_DAEMONS:
            group, cat, detail = MACOS_SYSTEM_DAEMONS[base_comm]
            res = (group, cat, base_comm, detail)
            LINEAGE_CACHE[pid] = (now, res)
            return res

        # Check known CLI tools
        if base_comm in MACOS_CLI_TOOLS:
            group, cat = MACOS_CLI_TOOLS[base_comm]
            res = (group, cat, base_comm, f"{base_comm} (CLI execution)")
            LINEAGE_CACHE[pid] = (now, res)
            return res

        # Query process path via libproc
        path = self.get_process_path(pid)
        if path:
            # 1. Is it inside a macOS .app bundle?
            # e.g., /Applications/Google Chrome.app/Contents/Frameworks/.../Google Chrome Helper (Renderer).app/...
            app_match = re.search(r"/(?:Applications|System/Applications|Users/[^/]+/Applications)/([^/]+)\.app", path)
            if app_match:
                app_name = app_match.group(1)
                detail = path.split("/")[-1]
                category = "browser" if any(b in app_name.lower() for b in ["chrome", "brave", "safari", "firefox", "edge", "zen", "arc"]) else "app"
                res = (app_name, category, base_comm, detail)
                LINEAGE_CACHE[pid] = (now, res)
                return res

            # 2. Is it in /System/Library or /usr/libexec?
            if path.startswith("/System/Library/") or path.startswith("/usr/libexec/"):
                binary_name = path.split("/")[-1]
                if binary_name in MACOS_SYSTEM_DAEMONS:
                    group, cat, detail = MACOS_SYSTEM_DAEMONS[binary_name]
                    res = (group, cat, binary_name, detail)
                else:
                    res = (f"macOS: {binary_name}", "system", base_comm, path)
                LINEAGE_CACHE[pid] = (now, res)
                return res

            # 3. User binary or Homebrew package
            detail = path.split("/")[-1]
            res = (base_comm, "cli", base_comm, detail)
            LINEAGE_CACHE[pid] = (now, res)
            return res

        # Fallback if path lookup failed (e.g. process terminated quickly)
        res = (base_comm, "app" if base_comm[0].isupper() else "cli", base_comm, base_comm)
        LINEAGE_CACHE[pid] = (now, res)
        return res


class NetworkStateDetector:
    """Detects active network interface, Wi-Fi SSID, and Personal Hotspot status."""

    HOTSPOT_KEYWORDS = ["iphone", "hotspot", "cellular", "galaxy", "pixel", "tether", "mobile", "portable"]

    def __init__(self):
        self.last_check = 0.0
        self.cached_state = ("Unknown", False)

    def get_network_state(self) -> Tuple[str, bool]:
        """
        Returns (network_name, is_hotspot).
        Cached for 4 seconds to eliminate command execution overhead.
        """
        now = time.time()
        if now - self.last_check < 4.0:
            return self.cached_state

        network_name = "Wi-Fi"
        is_hotspot = False

        if sys.platform == "darwin":
            # Attempt 1: Query airport binary for active Wi-Fi SSID
            airport_bin = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
            try:
                if os.path.exists(airport_bin):
                    res = subprocess.run([airport_bin, "-I"], capture_output=True, text=True, timeout=1.0)
                    for line in res.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("SSID:"):
                            network_name = line.split(":", 1)[1].strip()
                            break
                else:
                    # Attempt 2: networksetup fallback
                    res = subprocess.run(["networksetup", "-getairportnetwork", "en0"], capture_output=True, text=True, timeout=1.0)
                    if "Current Wi-Fi Network:" in res.stdout:
                        network_name = res.stdout.split(":", 1)[1].strip()
            except Exception:
                pass

        # Check for Hotspot indicators in SSID
        lower_name = network_name.lower()
        if any(kw in lower_name for kw in self.HOTSPOT_KEYWORDS):
            is_hotspot = True

        self.last_check = now
        self.cached_state = (network_name, is_hotspot)
        return self.cached_state


class MacLedgerStorage:
    """Manages SQLite storage, WAL configuration, dual-tier rollups, and Hotspot budgets."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._ensure_dir()
        self.conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        self._init_db()

    def _ensure_dir(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            fallback = Path.home() / "Library/Application Support/MacNetLedger/ledger.db"
            logger.warning("Permission denied for %s, falling back to %s", self.db_path, fallback)
            fallback.parent.mkdir(parents=True, exist_ok=True)
            self.db_path = fallback

    def _init_db(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")

        # Tier 1: 5-minute buckets (Retained for 14 days)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rollup_5min (
                bucket_ts     INTEGER NOT NULL,
                root_group    TEXT NOT NULL,
                category      TEXT NOT NULL,
                child_comm    TEXT NOT NULL,
                child_detail  TEXT NOT NULL,
                network_name  TEXT NOT NULL DEFAULT '',
                is_hotspot    INTEGER NOT NULL DEFAULT 0,
                rx_bytes      INTEGER DEFAULT 0,
                tx_bytes      INTEGER DEFAULT 0,
                PRIMARY KEY (bucket_ts, root_group, child_comm, child_detail, network_name)
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rollup_5min_ts ON rollup_5min(bucket_ts);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rollup_5min_hotspot ON rollup_5min(is_hotspot);")

        # Tier 2: 1-hour buckets (Retained for 400+ days)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rollup_1hour (
                bucket_ts     INTEGER NOT NULL,
                root_group    TEXT NOT NULL,
                category      TEXT NOT NULL,
                child_comm    TEXT NOT NULL,
                child_detail  TEXT NOT NULL,
                network_name  TEXT NOT NULL DEFAULT '',
                is_hotspot    INTEGER NOT NULL DEFAULT 0,
                rx_bytes      INTEGER DEFAULT 0,
                tx_bytes      INTEGER DEFAULT 0,
                PRIMARY KEY (bucket_ts, root_group, child_comm, child_detail, network_name)
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rollup_1hour_ts ON rollup_1hour(bucket_ts);")

        # Live Real-time rates (updated every 2 seconds for Menu Bar UI)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS live_state (
                updated_at    INTEGER NOT NULL,
                pid           INTEGER NOT NULL,
                root_group    TEXT NOT NULL,
                category      TEXT NOT NULL,
                child_comm    TEXT NOT NULL,
                child_detail  TEXT NOT NULL,
                rx_rate       REAL DEFAULT 0,
                tx_rate       REAL DEFAULT 0,
                PRIMARY KEY (pid)
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS live_summary (
                id                  INTEGER PRIMARY KEY CHECK (id = 1),
                updated_at          INTEGER NOT NULL,
                rx_rate             REAL DEFAULT 0,
                tx_rate             REAL DEFAULT 0,
                top_process         TEXT DEFAULT '',
                top_category        TEXT DEFAULT '',
                network_name        TEXT DEFAULT '',
                is_hotspot          INTEGER DEFAULT 0,
                hotspot_today_bytes INTEGER DEFAULT 0
            );
        """)

        # Hotspot Daily Budget tracker
        cur.execute("""
            CREATE TABLE IF NOT EXISTS hotspot_budget (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                daily_budget_bytes INTEGER DEFAULT 3221225472,
                today_bytes        INTEGER DEFAULT 0,
                last_reset_day     TEXT DEFAULT ''
            );
        """)

        # Seed initial row for budget if not exists
        cur.execute("""
            INSERT OR IGNORE INTO hotspot_budget (id, daily_budget_bytes, today_bytes, last_reset_day)
            VALUES (1, 3221225472, 0, ?);
        """, (datetime.date.today().isoformat(),))

        self.conn.commit()
        self._ensure_file_permissions()

    def _ensure_file_permissions(self):
        """Ensures ledger DB and WAL files are world-readable for unprivileged UI access."""
        for p in [self.db_path, self.db_path.with_name(self.db_path.name + "-wal"), self.db_path.with_name(self.db_path.name + "-shm")]:
            try:
                if p.exists():
                    os.chmod(p, 0o666)
            except Exception as e:
                logger.debug("Could not chmod %s: %s", p, e)

    def record_deltas(self, deltas: Dict[Tuple[int, str, str, str, str, str, int], Tuple[int, int]]):
        """
        Commits byte deltas to rollup_5min.
        Key: (bucket_ts, root_group, category, child_comm, child_detail, network_name, is_hotspot)
        Value: (rx_bytes, tx_bytes)
        """
        if not deltas:
            return

        cur = self.conn.cursor()
        sql = """
            INSERT INTO rollup_5min (bucket_ts, root_group, category, child_comm, child_detail, network_name, is_hotspot, rx_bytes, tx_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bucket_ts, root_group, child_comm, child_detail, network_name) DO UPDATE SET
                rx_bytes = rollup_5min.rx_bytes + excluded.rx_bytes,
                tx_bytes = rollup_5min.tx_bytes + excluded.tx_bytes;
        """
        rows = [
            (bucket_ts, root_group, category, child_comm, child_detail, net_name, is_hs, rx, tx)
            for (bucket_ts, root_group, category, child_comm, child_detail, net_name, is_hs), (rx, tx) in deltas.items()
        ]
        cur.executemany(sql, rows)
        self.conn.commit()

    def update_live_state(
        self,
        live_records: list,
        total_rx_rate: float,
        total_tx_rate: float,
        top_process: str,
        top_category: str,
        network_name: str,
        is_hotspot: bool,
        hotspot_today_bytes: int
    ):
        """Updates instantaneous live rates and summary state."""
        cur = self.conn.cursor()
        now = int(time.time())

        cur.execute("DELETE FROM live_state;")
        if live_records:
            sql = """
                INSERT OR REPLACE INTO live_state (updated_at, pid, root_group, category, child_comm, child_detail, rx_rate, tx_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            cur.executemany(sql, [(now, r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in live_records])

        cur.execute("""
            INSERT OR REPLACE INTO live_summary (id, updated_at, rx_rate, tx_rate, top_process, top_category, network_name, is_hotspot, hotspot_today_bytes)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now, total_rx_rate, total_tx_rate, top_process, top_category, network_name, 1 if is_hotspot else 0, hotspot_today_bytes))
        self.conn.commit()

    def update_hotspot_budget(self, delta_bytes: int) -> int:
        """Accumulates mobile hotspot consumption for today and resets on day boundary."""
        cur = self.conn.cursor()
        today_iso = datetime.date.today().isoformat()

        cur.execute("SELECT daily_budget_bytes, today_bytes, last_reset_day FROM hotspot_budget WHERE id = 1;")
        row = cur.fetchone()
        budget, current_today, last_reset = row if row else (3221225472, 0, today_iso)

        if last_reset != today_iso:
            current_today = 0
            last_reset = today_iso

        current_today += delta_bytes
        cur.execute("""
            UPDATE hotspot_budget
            SET today_bytes = ?, last_reset_day = ?
            WHERE id = 1;
        """, (current_today, last_reset))
        self.conn.commit()
        return current_today

    def prune_and_rollup(self):
        """
        Rolls up 5-minute buckets older than 1 hour into 1-hour buckets and prunes retention.
        - rollup_5min retention: 14 days
        - rollup_1hour retention: 400 days
        """
        cur = self.conn.cursor()
        now = int(time.time())
        one_hour_ago = now - 3600
        fourteen_days_ago = now - (14 * 86400)
        four_hundred_days_ago = now - (400 * 86400)

        # 1. Rollup 5min buckets older than 1 hour into rollup_1hour
        rollup_sql = """
            INSERT INTO rollup_1hour (bucket_ts, root_group, category, child_comm, child_detail, network_name, is_hotspot, rx_bytes, tx_bytes)
            SELECT
                (bucket_ts / 3600) * 3600 AS h_bucket,
                root_group,
                category,
                child_comm,
                child_detail,
                network_name,
                is_hotspot,
                SUM(rx_bytes),
                SUM(tx_bytes)
            FROM rollup_5min
            WHERE bucket_ts <= ?
            GROUP BY h_bucket, root_group, child_comm, child_detail, network_name, is_hotspot
            ON CONFLICT(bucket_ts, root_group, child_comm, child_detail, network_name) DO UPDATE SET
                rx_bytes = excluded.rx_bytes,
                tx_bytes = excluded.tx_bytes;
        """
        cur.execute(rollup_sql, (one_hour_ago,))

        # 2. Prune rollup_5min older than 14 days
        cur.execute("DELETE FROM rollup_5min WHERE bucket_ts < ?;", (fourteen_days_ago,))

        # 3. Prune rollup_1hour older than 400 days
        cur.execute("DELETE FROM rollup_1hour WHERE bucket_ts < ?;", (four_hundred_days_ago,))

        self.conn.commit()
        self._ensure_file_permissions()
        logger.info("Executed database maintenance and retention pruning.")


class NetTopParser:
    """Parses streaming CSV output from macOS `/usr/bin/nettop`."""

    @staticmethod
    def parse_line(line: str) -> Optional[Tuple[str, int, int, int, str]]:
        """
        Parses a single line of nettop CSV output.
        Format emitted by: nettop -P -d -s 2 -L 0 -J bytes_in,bytes_out,interface
        Expected fields: <timestamp>,<proc_name>.<pid>,<bytes_in>,<bytes_out>[,<interface>]
        Returns: (comm, pid, bytes_in, bytes_out, interface)
        """
        line = line.strip()
        if not line or line.startswith("time") or line.startswith("bytes_in") or line.startswith("==="):
            return None

        parts = [p.strip() for p in line.split(",")]
        # Needs at least: [time, proc.pid, bytes_in, bytes_out]
        if len(parts) < 4:
            return None

        proc_target = parts[1]
        if "." not in proc_target:
            return None

        # Split from the right for PID in case app name contains dots
        comm, pid_str = proc_target.rsplit(".", 1)
        if not pid_str.isdigit():
            return None

        pid = int(pid_str)

        try:
            rx_bytes = int(float(parts[2]))
            tx_bytes = int(float(parts[3]))
        except ValueError:
            return None

        interface = parts[4] if len(parts) > 4 else "en0"
        return comm, pid, rx_bytes, tx_bytes, interface


class NetTopCollector:
    """Streams live network throughput from macOS nettop."""

    def __init__(self, interval: int = 2):
        self.interval = max(1, interval)
        self.process = None

    def start(self):
        cmd = [
            "/usr/bin/nettop",
            "-P",
            "-d",
            "-s", str(self.interval),
            "-L", "0",
            "-J", "bytes_in,bytes_out,interface"
        ]
        logger.info("Starting nettop stream: %s", " ".join(cmd))
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()
            self.process = None


def main():
    parser = argparse.ArgumentParser(description="MacNetLedger Background Telemetry Daemon")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite ledger database")
    parser.add_argument("--interval", type=int, default=2, help="Sampling interval in seconds (default: 2)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    logger.info("Initializing MacNetLedger Daemon (macnetledgerd)...")
    storage = MacLedgerStorage(args.db)
    resolver = DarwinProcessResolver()
    net_detector = NetworkStateDetector()
    collector = NetTopCollector(interval=args.interval)

    # State tracking
    running = True

    def sig_handler(signum, frame):
        nonlocal running
        logger.info("Received termination signal (%d). Shutting down cleanly...", signum)
        running = False

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    collector.start()

    last_prune_time = time.time()
    last_flush_time = time.time()
    pending_deltas: Dict[Tuple[int, str, str, str, str, str, int], Tuple[int, int]] = {}

    # Sample batch buffer
    current_tick_records: List[Tuple[int, str, str, str, str, float, float]] = []

    try:
        while running and collector.process and collector.process.stdout:
            # Non-blocking wait for next nettop line
            r, _, _ = select.select([collector.process.stdout], [], [], 1.0)
            if not r:
                continue

            line = collector.process.stdout.readline()
            if not line:
                if collector.process.poll() is not None:
                    logger.warning("nettop exited with code %s. Restarting...", collector.process.returncode)
                    collector.start()
                continue

            parsed = NetTopParser.parse_line(line)
            if not parsed:
                continue

            comm, pid, rx_bytes, tx_bytes, interface = parsed
            # Ignore zero-delta ticks
            if rx_bytes == 0 and tx_bytes == 0:
                continue

            now = time.time()
            network_name, is_hotspot = net_detector.get_network_state()
            root_group, category, child_comm, child_detail = resolver.resolve(pid, comm)

            # Bucket timestamp aligned to 5 minutes (300 seconds)
            bucket_ts = (int(now) // 300) * 300
            key = (bucket_ts, root_group, category, child_comm, child_detail, network_name, 1 if is_hotspot else 0)

            # Accumulate in 5-minute rollup deltas
            prev_rx, prev_tx = pending_deltas.get(key, (0, 0))
            pending_deltas[key] = (prev_rx + rx_bytes, prev_tx + tx_bytes)

            # Convert to rates (bytes per second)
            rx_rate = rx_bytes / args.interval
            tx_rate = tx_bytes / args.interval
            current_tick_records.append((pid, root_group, category, child_comm, child_detail, rx_rate, tx_rate))

            # Update hotspot budget if on hotspot
            hotspot_today = 0
            if is_hotspot:
                hotspot_today = storage.update_hotspot_budget(rx_bytes + tx_bytes)

            # Periodic commit to SQLite (every 2-4 seconds)
            if now - last_flush_time >= args.interval:
                if pending_deltas:
                    storage.record_deltas(pending_deltas)
                    pending_deltas.clear()

                # Calculate live rates and top hog
                total_rx_rate = sum(r[5] for r in current_tick_records)
                total_tx_rate = sum(r[6] for r in current_tick_records)

                top_process = ""
                top_category = ""
                if current_tick_records:
                    top_record = max(current_tick_records, key=lambda r: r[5] + r[6])
                    if (top_record[5] + top_record[6]) > 1024:  # At least 1 KB/s to trigger top label
                        top_process = top_record[1]
                        top_category = top_record[2]

                storage.update_live_state(
                    current_tick_records,
                    total_rx_rate,
                    total_tx_rate,
                    top_process,
                    top_category,
                    network_name,
                    is_hotspot,
                    hotspot_today
                )

                current_tick_records.clear()
                last_flush_time = now

            # Maintenance pruning and 1-hour rollups every 30 minutes
            if now - last_prune_time >= 1800:
                storage.prune_and_rollup()
                last_prune_time = now

    except Exception as e:
        logger.exception("Unexpected error in daemon main loop: %s", e)
    finally:
        collector.stop()
        if pending_deltas:
            storage.record_deltas(pending_deltas)
        logger.info("MacNetLedger Daemon stopped cleanly.")


if __name__ == "__main__":
    main()
