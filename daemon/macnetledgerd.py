#!/usr/bin/env python3
"""
MacNetLedger Daemon (macnetledgerd)
System-wide process lineage bandwidth ledger & mobile hotspot guardian for macOS Monterey (12.7+) and beyond.

Uses Darwin native nettop snapshot diagnostics, libproc path attribution,
and dual-tier SQLite time-series rollups in WAL mode.
"""

import argparse
import ctypes
import datetime
import logging
import os
import plistlib
import re
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

LINEAGE_CACHE: Dict[int, Tuple[float, Tuple[str, str, str, str]]] = {}
CACHE_TTL_SEC = 5.0


def parse_byte_value(val: str) -> int:
    """Parses a string representing bytes or human-readable format (e.g. '154820', '4.2 MiB', '153 KiB')."""
    val = val.strip().replace(",", "")
    if not val:
        return 0
    try:
        return int(val)
    except ValueError:
        pass

    match = re.match(r"^([\d.]+)\s*([A-Za-z]+)?$", val)
    if not match:
        return 0

    num = float(match.group(1))
    unit = (match.group(2) or "").upper()
    multiplier = 1
    if unit in ("K", "KB", "KIB"):
        multiplier = 1024
    elif unit in ("M", "MB", "MIB"):
        multiplier = 1024 * 1024
    elif unit in ("G", "GB", "GIB"):
        multiplier = 1024 * 1024 * 1024
    elif unit in ("T", "TB", "TIB"):
        multiplier = 1024 * 1024 * 1024 * 1024
    return int(num * multiplier)


def parse_nettop_text_line(line: str) -> Optional[Tuple[str, int, int, int]]:
    """
    Parses a single line of nettop text/CSV output into (comm, pid, rx_bytes, tx_bytes).
    Handles:
      Google Chrome.3821   48291024   1284920
      Telegram.15820       154820     42300
      safari.1234,1245890,45210
      Telegram.15820   en0   154820   42300
    """
    line = line.strip().strip(",")
    if not line or "bytes_in" in line or line.startswith("===") or line.startswith("time") or line.startswith("process"):
        return None

    if "," in line:
        parts = [p.strip() for p in line.split(",") if p.strip()]
    else:
        parts = line.split()

    if len(parts) < 3:
        return None

    # Handle cases where unit is separated by space, e.g. "150 KiB 40 KiB"
    if parts[-1].upper() in ("B", "KB", "KIB", "MB", "MIB", "GB", "GIB", "TB", "TIB") and len(parts) >= 5:
        tx_str = parts[-2] + parts[-1]
        if parts[-3].upper() in ("B", "KB", "KIB", "MB", "MIB", "GB", "GIB", "TB", "TIB"):
            rx_str = parts[-4] + parts[-3]
            proc_parts = parts[:-4]
        else:
            rx_str = parts[-3]
            proc_parts = parts[:-3]
    else:
        rx_str = parts[-2]
        tx_str = parts[-1]
        proc_parts = parts[:-2]

    rx_val = parse_byte_value(rx_str)
    tx_val = parse_byte_value(tx_str)

    # Filter out interface names like en0, pdp_ip0, etc. if attached
    if len(proc_parts) > 1 and re.match(r"^(en\d+|pdp_ip\d+|lo\d+|utun\d+|awdl\d+|llw\d+|bridge\d+|ap\d+)$", proc_parts[-1]):
        proc_parts = proc_parts[:-1]

    proc_str = " ".join(proc_parts)
    if "." not in proc_str:
        return None

    comm, pid_str = proc_str.rsplit(".", 1)
    if not pid_str.isdigit():
        return None

    pid = int(pid_str)
    return (comm.strip(), pid, rx_val, tx_val)


def extract_nettop_processes(data) -> List[Tuple[str, int, int, int]]:
    """Extracts (comm, pid, bytes_in, bytes_out) from parsed nettop XML plist."""
    entries = []
    candidates = []
    if isinstance(data, dict):
        for k in ["Processes", "processes", "nettop", "entries"]:
            if k in data and isinstance(data[k], list):
                candidates = data[k]
                break
        if not candidates and "interfaces" in data and isinstance(data["interfaces"], list):
            for iface in data["interfaces"]:
                if isinstance(iface, dict) and "processes" in iface:
                    candidates.extend(iface["processes"])
    elif isinstance(data, list):
        candidates = data

    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("process_name") or "")
        pid = int(item.get("pid") or 0)
        if not pid and "." in name:
            parts = name.rsplit(".", 1)
            if parts[1].isdigit():
                name = parts[0]
                pid = int(parts[1])
        rx = int(item.get("bytes_in", 0))
        tx = int(item.get("bytes_out", 0))
        if name and pid:
            entries.append((name, pid, rx, tx))
    return entries


class NetTopParser:
    """Fallback parser for legacy CSV output formats."""

    @staticmethod
    def parse_line(line: str) -> Optional[Tuple[str, int, int, int, str]]:
        line = line.strip()
        if not line or line.startswith("time") or line.startswith("bytes_in") or line.startswith("==="):
            return None

        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            return None

        proc_target = parts[1]
        if "." not in proc_target:
            return None

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
        if not self._proc_pidpath or pid <= 0:
            return None
        buf = ctypes.create_string_buffer(4096)
        ret = self._proc_pidpath(pid, buf, 4096)
        if ret > 0:
            return buf.value.decode("utf-8", errors="replace")
        return None

    def resolve(self, pid: int, raw_comm: str) -> Tuple[str, str, str, str]:
        now = time.time()
        if pid in LINEAGE_CACHE:
            ts, cached = LINEAGE_CACHE[pid]
            if now - ts < CACHE_TTL_SEC:
                return cached

        base_comm = raw_comm.split("/")[-1].strip()
        if base_comm in MACOS_SYSTEM_DAEMONS:
            group, cat, detail = MACOS_SYSTEM_DAEMONS[base_comm]
            res = (group, cat, base_comm, detail)
            LINEAGE_CACHE[pid] = (now, res)
            return res

        if base_comm in MACOS_CLI_TOOLS:
            group, cat = MACOS_CLI_TOOLS[base_comm]
            res = (group, cat, base_comm, f"{base_comm} (CLI execution)")
            LINEAGE_CACHE[pid] = (now, res)
            return res

        path = self.get_process_path(pid)
        if path:
            app_match = re.search(r"/(?:Applications|System/Applications|Users/[^/]+/Applications)/([^/]+)\.app", path)
            if app_match:
                app_name = app_match.group(1)
                detail = path.split("/")[-1]
                category = "browser" if any(b in app_name.lower() for b in ["chrome", "brave", "safari", "firefox", "edge", "zen", "arc"]) else "app"
                res = (app_name, category, base_comm, detail)
                LINEAGE_CACHE[pid] = (now, res)
                return res

            if path.startswith("/System/Library/") or path.startswith("/usr/libexec/"):
                binary_name = path.split("/")[-1]
                if binary_name in MACOS_SYSTEM_DAEMONS:
                    group, cat, detail = MACOS_SYSTEM_DAEMONS[binary_name]
                    res = (group, cat, binary_name, detail)
                else:
                    res = (f"macOS: {binary_name}", "system", base_comm, path)
                LINEAGE_CACHE[pid] = (now, res)
                return res

            detail = path.split("/")[-1]
            res = (base_comm, "cli", base_comm, detail)
            LINEAGE_CACHE[pid] = (now, res)
            return res

        res = (base_comm, "app" if base_comm[0].isupper() else "cli", base_comm, base_comm)
        LINEAGE_CACHE[pid] = (now, res)
        return res


class NetworkStateDetector:
    """Detects active network interface, Wi-Fi SSID, and Personal Hotspot status."""

    HOTSPOT_KEYWORDS = ["iphone", "hotspot", "cellular", "galaxy", "pixel", "tether", "mobile", "portable"]

    def __init__(self):
        self.last_check = 0.0
        self.cached_state = ("Wi-Fi", False)

    def get_network_state(self) -> Tuple[str, bool]:
        now = time.time()
        if now - self.last_check < 4.0:
            return self.cached_state

        network_name = "Wi-Fi"
        is_hotspot = False

        if sys.platform == "darwin":
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
                    res = subprocess.run(["networksetup", "-getairportnetwork", "en0"], capture_output=True, text=True, timeout=1.0)
                    if "Current Wi-Fi Network:" in res.stdout:
                        network_name = res.stdout.split(":", 1)[1].strip()
            except Exception:
                pass

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
            os.chmod(self.db_path.parent, 0o777)
        except Exception:
            pass

    def _init_db(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")

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

        cur.execute("""
            CREATE TABLE IF NOT EXISTS hotspot_budget (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                daily_budget_bytes INTEGER DEFAULT 3221225472,
                today_bytes        INTEGER DEFAULT 0,
                last_reset_day     TEXT DEFAULT ''
            );
        """)

        cur.execute("""
            INSERT OR IGNORE INTO hotspot_budget (id, daily_budget_bytes, today_bytes, last_reset_day)
            VALUES (1, 3221225472, 0, ?);
        """, (datetime.date.today().isoformat(),))

        # Seed initial empty summary if not exists
        cur.execute("""
            INSERT OR IGNORE INTO live_summary (id, updated_at, rx_rate, tx_rate, top_process, top_category, network_name, is_hotspot, hotspot_today_bytes)
            VALUES (1, ?, 0, 0, '', '', 'Wi-Fi', 0, 0);
        """, (int(time.time()),))

        self.conn.commit()
        self._ensure_file_permissions()

    def _ensure_file_permissions(self):
        try:
            if self.db_path.parent.exists():
                os.chmod(self.db_path.parent, 0o777)
        except Exception:
            pass
        for p in [self.db_path, self.db_path.with_name(self.db_path.name + "-wal"), self.db_path.with_name(self.db_path.name + "-shm")]:
            try:
                if p.exists():
                    os.chmod(p, 0o666)
            except Exception:
                pass

    def record_deltas(self, deltas: Dict[Tuple[int, str, str, str, str, str, int], Tuple[int, int]]):
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
        self._ensure_file_permissions()

    def update_hotspot_budget(self, delta_bytes: int) -> int:
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
        cur = self.conn.cursor()
        now = int(time.time())
        one_hour_ago = now - 3600
        fourteen_days_ago = now - (14 * 86400)
        four_hundred_days_ago = now - (400 * 86400)

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
        cur.execute("DELETE FROM rollup_5min WHERE bucket_ts < ?;", (fourteen_days_ago,))
        cur.execute("DELETE FROM rollup_1hour WHERE bucket_ts < ?;", (four_hundred_days_ago,))
        self.conn.commit()
        self._ensure_file_permissions()


class NetTopSnapshotCollector:
    """Takes periodic non-blocking snapshots using `/usr/bin/nettop`."""

    def __init__(self):
        self.last_totals: Dict[int, Tuple[int, int]] = {}
        self.last_time = time.time()
        self._working_cmd: Optional[List[str]] = ["/usr/bin/nettop", "-P", "-L", "1", "-J", "bytes_in,bytes_out"]

    def _execute_nettop(self) -> Tuple[int, bytes, bytes]:
        candidates = [
            ["/usr/bin/nettop", "-P", "-L", "1", "-J", "bytes_in,bytes_out"],
            ["/usr/bin/nettop", "-P", "-l", "1", "-J", "bytes_in,bytes_out"],
            ["/usr/bin/nettop", "-P", "-L", "1"],
            ["/usr/bin/nettop", "-P", "-l", "1"],
        ]

        if self._working_cmd:
            candidates = [self._working_cmd] + [c for c in candidates if c != self._working_cmd]

        for cmd in candidates:
            try:
                res = subprocess.run(cmd, capture_output=True, timeout=2.0)
                if res.returncode == 0 and res.stdout and len(res.stdout) > 20:
                    self._working_cmd = cmd
                    return res.returncode, res.stdout, res.stderr
            except Exception as e:
                logger.debug("nettop candidate %s failed: %s", cmd, e)

        return 1, b"", b"All nettop variants failed"

    def sample(self) -> List[Tuple[str, int, int, int]]:
        """
        Runs nettop for 1 snapshot, calculates deltas since last sample.
        Returns: list of (comm, pid, rx_delta, tx_delta)
        """
        now = time.time()
        self.last_time = now

        returncode, stdout, stderr = self._execute_nettop()
        if returncode != 0 or not stdout:
            if stderr:
                logger.warning("nettop snapshot error: %s", stderr.decode("utf-8", errors="ignore")[:200])
            return []

        current_entries: List[Tuple[str, int, int, int]] = []

        # 1. Attempt XML/binary plist decoding if it has plist signatures
        if stdout.lstrip().startswith(b"<?xml") or stdout.startswith(b"bplist"):
            try:
                data = plistlib.loads(stdout)
                current_entries = extract_nettop_processes(data)
            except Exception as e:
                logger.debug("plist parsing error: %s", e)

        # 2. If not plist (or plist returned empty), parse as line-based text/CSV
        if not current_entries:
            text = stdout.decode("utf-8", errors="ignore")
            for line in text.splitlines():
                parsed = parse_nettop_text_line(line)
                if parsed:
                    current_entries.append(parsed)

        if not current_entries:
            logger.debug("nettop returned output (%d bytes) but 0 entries parsed.", len(stdout))
            return []

        deltas = []
        current_pids = set()

        for comm, pid, rx_total, tx_total in current_entries:
            current_pids.add(pid)
            if pid in self.last_totals:
                prev_rx, prev_tx = self.last_totals[pid]
                rx_delta = max(0, rx_total - prev_rx)
                tx_delta = max(0, tx_total - prev_tx)
            else:
                rx_delta = 0
                tx_delta = 0

            self.last_totals[pid] = (rx_total, tx_total)
            deltas.append((comm, pid, rx_delta, tx_delta))

        # Evict terminated PIDs from cache
        for old_pid in list(self.last_totals.keys()):
            if old_pid not in current_pids:
                del self.last_totals[old_pid]

        return deltas


def main():
    try:
        os.umask(0)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="MacNetLedger Background Telemetry Daemon")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite ledger database")
    parser.add_argument("--interval", type=int, default=1, help="Sampling interval in seconds (default: 1)")
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
    collector = NetTopSnapshotCollector()

    running = True

    def sig_handler(signum, frame):
        nonlocal running
        logger.info("Received termination signal (%d). Shutting down cleanly...", signum)
        running = False

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    last_prune_time = time.time()
    pending_deltas: Dict[Tuple[int, str, str, str, str, str, int], Tuple[int, int]] = {}

    while running:
        tick_start = time.time()
        try:
            deltas = collector.sample()
            now = time.time()

            network_name, is_hotspot = net_detector.get_network_state()
            current_tick_records = []
            tick_hotspot_bytes = 0

            for comm, pid, rx_bytes, tx_bytes in deltas:
                if rx_bytes == 0 and tx_bytes == 0:
                    continue

                root_group, category, child_comm, child_detail = resolver.resolve(pid, comm)
                bucket_ts = (int(now) // 300) * 300
                key = (bucket_ts, root_group, category, child_comm, child_detail, network_name, 1 if is_hotspot else 0)

                prev_rx, prev_tx = pending_deltas.get(key, (0, 0))
                pending_deltas[key] = (prev_rx + rx_bytes, prev_tx + tx_bytes)

                rx_rate = rx_bytes / args.interval
                tx_rate = tx_bytes / args.interval
                current_tick_records.append((pid, root_group, category, child_comm, child_detail, rx_rate, tx_rate))

                if is_hotspot:
                    tick_hotspot_bytes += (rx_bytes + tx_bytes)

            if pending_deltas:
                storage.record_deltas(pending_deltas)
                pending_deltas.clear()

            hotspot_today = 0
            if tick_hotspot_bytes > 0:
                hotspot_today = storage.update_hotspot_budget(tick_hotspot_bytes)

            total_rx_rate = sum(r[5] for r in current_tick_records)
            total_tx_rate = sum(r[6] for r in current_tick_records)

            top_process = ""
            top_category = ""
            if current_tick_records:
                top_record = max(current_tick_records, key=lambda r: r[5] + r[6])
                if (top_record[5] + top_record[6]) > 1024:
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

            if now - last_prune_time >= 1800:
                storage.prune_and_rollup()
                last_prune_time = now
        except Exception as e:
            logger.exception("Unexpected error in daemon main tick: %s", e)

        # Sleep remaining time to maintain consistent interval
        elapsed = time.time() - tick_start
        sleep_time = max(0.2, float(args.interval) - elapsed)
        time.sleep(sleep_time)

    logger.info("MacNetLedger Daemon stopped cleanly.")


if __name__ == "__main__":
    main()
