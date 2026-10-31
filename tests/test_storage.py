#!/usr/bin/env python3
"""
Unit tests for MacLedgerStorage in MacNetLedger.
"""

import os
import sqlite3
import tempfile
import time
import unittest
from daemon.macnetledgerd import MacLedgerStorage


class TestMacLedgerStorage(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_ledger.db")
        self.storage = MacLedgerStorage(self.db_path)

    def tearDown(self):
        self.storage.conn.close()
        self.tmp_dir.cleanup()

    def test_schema_initialization(self):
        cur = self.storage.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cur.fetchall()}

        self.assertIn("rollup_5min", tables)
        self.assertIn("rollup_1hour", tables)
        self.assertIn("live_state", tables)
        self.assertIn("live_summary", tables)
        self.assertIn("hotspot_budget", tables)

        cur.execute("PRAGMA journal_mode;")
        mode = cur.fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_record_deltas_and_accumulation(self):
        bucket_ts = 1700000000
        deltas = {
            (bucket_ts, "Google Chrome", "browser", "Google Chrome Helper", "Renderer", "Home-WiFi", 0): (1000, 200)
        }
        self.storage.record_deltas(deltas)

        cur = self.storage.conn.cursor()
        cur.execute("SELECT rx_bytes, tx_bytes FROM rollup_5min WHERE bucket_ts = ?;", (bucket_ts,))
        row = cur.fetchone()
        self.assertEqual(row, (1000, 200))

        # Add additional bytes to same bucket -> must accumulate
        deltas_add = {
            (bucket_ts, "Google Chrome", "browser", "Google Chrome Helper", "Renderer", "Home-WiFi", 0): (500, 100)
        }
        self.storage.record_deltas(deltas_add)

        cur.execute("SELECT rx_bytes, tx_bytes FROM rollup_5min WHERE bucket_ts = ?;", (bucket_ts,))
        row = cur.fetchone()
        self.assertEqual(row, (1500, 300))

    def test_update_live_state_and_summary(self):
        live_records = [
            (4120, "Google Chrome", "browser", "Google Chrome Helper", "Renderer", 250000.0, 15000.0)
        ]
        self.storage.update_live_state(
            live_records,
            total_rx_rate=250000.0,
            total_tx_rate=15000.0,
            top_process="Google Chrome",
            top_category="browser",
            network_name="Zenmi's iPhone",
            is_hotspot=True,
            hotspot_today_bytes=52428800
        )

        cur = self.storage.conn.cursor()
        cur.execute("SELECT rx_rate, tx_rate, top_process, is_hotspot, network_name FROM live_summary WHERE id = 1;")
        row = cur.fetchone()
        self.assertEqual(row[0], 250000.0)
        self.assertEqual(row[1], 15000.0)
        self.assertEqual(row[2], "Google Chrome")
        self.assertEqual(row[3], 1)
        self.assertEqual(row[4], "Zenmi's iPhone")

    def test_hotspot_budget_accumulation(self):
        # Accumulate 100 MB
        used = self.storage.update_hotspot_budget(100 * 1024 * 1024)
        self.assertEqual(used, 100 * 1024 * 1024)

        # Accumulate another 50 MB
        used = self.storage.update_hotspot_budget(50 * 1024 * 1024)
        self.assertEqual(used, 150 * 1024 * 1024)

    def test_rollup_1hour_aggregation(self):
        cur = self.storage.conn.cursor()
        now = int(time.time())
        two_hours_ago = now - 7200
        # Align to 5-min
        bucket_1 = (two_hours_ago // 300) * 300
        bucket_2 = bucket_1 + 300

        deltas = {
            (bucket_1, "cURL", "cli", "curl", "curl fetch", "Zenmi's iPhone", 1): (2000, 500),
            (bucket_2, "cURL", "cli", "curl", "curl fetch", "Zenmi's iPhone", 1): (3000, 800),
        }
        self.storage.record_deltas(deltas)

        # Run rollup
        self.storage.prune_and_rollup()

        cur.execute("SELECT rx_bytes, tx_bytes, is_hotspot FROM rollup_1hour WHERE root_group = 'cURL';")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 5000)
        self.assertEqual(row[1], 1300)
        self.assertEqual(row[2], 1)


if __name__ == "__main__":
    unittest.main()
