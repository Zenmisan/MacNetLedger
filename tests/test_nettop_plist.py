#!/usr/bin/env python3
"""
Tests for Plist and Text-based nettop parsing in MacNetLedger.
"""

import plistlib
import unittest
from daemon.macnetledgerd import extract_nettop_processes, parse_byte_value, parse_nettop_text_line


class TestNettopParsers(unittest.TestCase):
    def test_parse_byte_value(self):
        self.assertEqual(parse_byte_value("154820"), 154820)
        self.assertEqual(parse_byte_value("1,245,890"), 1245890)
        self.assertEqual(parse_byte_value("153 KiB"), 153 * 1024)
        self.assertEqual(parse_byte_value("4.5 MiB"), int(4.5 * 1024 * 1024))
        self.assertEqual(parse_byte_value("2.0 GiB"), 2 * 1024 * 1024 * 1024)
        self.assertEqual(parse_byte_value(""), 0)
        self.assertEqual(parse_byte_value("invalid"), 0)

    def test_parse_nettop_text_line(self):
        # Space-separated raw numbers
        line1 = "Telegram.15820       154820     42300"
        res1 = parse_nettop_text_line(line1)
        self.assertEqual(res1, ("Telegram", 15820, 154820, 42300))

        # Space-separated with space in process name
        line2 = "Google Chrome.3821   48291024   1284920"
        res2 = parse_nettop_text_line(line2)
        self.assertEqual(res2, ("Google Chrome", 3821, 48291024, 1284920))

        # Interface included
        line3 = "Telegram.15820   en0   154820   42300"
        res3 = parse_nettop_text_line(line3)
        self.assertEqual(res3, ("Telegram", 15820, 154820, 42300))

        # Comma-separated with trailing comma (real Darwin Monterey nettop output)
        line4 = "Telegram.17231,125247,25256,"
        res4 = parse_nettop_text_line(line4)
        self.assertEqual(res4, ("Telegram", 17231, 125247, 25256))

        line4b = "Google Chrome H.767,700218,50151,"
        res4b = parse_nettop_text_line(line4b)
        self.assertEqual(res4b, ("Google Chrome H", 767, 700218, 50151))

        # Header with commas
        self.assertIsNone(parse_nettop_text_line(",bytes_in,bytes_out,"))

        # Human-readable suffixes
        line5 = "Telegram.15820   150 KiB   40 KiB"
        res5 = parse_nettop_text_line(line5)
        self.assertEqual(res5, ("Telegram", 15820, 150 * 1024, 40 * 1024))

        # Headers and invalid lines should be skipped
        self.assertIsNone(parse_nettop_text_line("bytes_in    bytes_out"))
        self.assertIsNone(parse_nettop_text_line("process    state    bytes_in    bytes_out"))
        self.assertIsNone(parse_nettop_text_line("========================================"))
        self.assertIsNone(parse_nettop_text_line(""))

    def test_extract_from_processes_list(self):
        sample_dict = {
            "Time": "2026-10-31 11:20:00",
            "Processes": [
                {"name": "Google Chrome", "pid": 4120, "bytes_in": 150000, "bytes_out": 25000},
                {"name": "nsurlsessiond", "pid": 318, "bytes_in": 980000, "bytes_out": 4000},
            ]
        }
        res = extract_nettop_processes(sample_dict)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0], ("Google Chrome", 4120, 150000, 25000))
        self.assertEqual(res[1], ("nsurlsessiond", 318, 980000, 4000))

    def test_extract_from_nettop_key(self):
        sample_dict = {
            "Time": "2026-10-31 11:20:00",
            "nettop": [
                {"name": "Safari.120", "bytes_in": 40000, "bytes_out": 8000}
            ]
        }
        res = extract_nettop_processes(sample_dict)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0], ("Safari", 120, 40000, 8000))

    def test_parse_netstat_link_line(self):
        from daemon.macnetledgerd import parse_netstat_link_line

        line_en0 = "en0   1500  <Link#4>    38:f9:d3:01:23:45  450000     0  350000000   280000     0   45000000     0"
        parsed_en0 = parse_netstat_link_line(line_en0)
        self.assertIsNotNone(parsed_en0)
        iface, rx, tx = parsed_en0
        self.assertEqual(iface, "en0")
        self.assertEqual(rx, 350000000)
        self.assertEqual(tx, 45000000)

        line_lo0 = "lo0   16384 <Link#1>                         1200     0     150000     1200     0     150000     0"
        parsed_lo0 = parse_netstat_link_line(line_lo0)
        self.assertIsNotNone(parsed_lo0)
        self.assertEqual(parsed_lo0, ("lo0", 150000, 150000))

        # Non-link line should return None
        line_inet = "en0   1500  192.168.1     192.168.1.100      450000     -  350000000   280000     -   45000000     -"
        self.assertIsNone(parse_netstat_link_line(line_inet))

    def test_collector_credits_runtime_spawned_pids(self):
        from daemon.macnetledgerd import NetTopSnapshotCollector
        from unittest.mock import patch

        collector = NetTopSnapshotCollector()

        # Tick 1 (Boot baseline): Spotify is already running with 50,000 bytes
        mock_stdout_tick1 = b"Spotify.500,50000,10000,\n"
        with patch.object(collector, "_execute_nettop", return_value=(0, mock_stdout_tick1, b"")):
            deltas = collector.sample()
            self.assertEqual(len(deltas), 1)
            comm, pid, rx_delta, tx_delta = deltas[0]
            # Boot baseline must have 0 delta so pre-boot data isn't counted as a spike
            self.assertEqual(rx_delta, 0)
            self.assertEqual(tx_delta, 0)

        # Tick 2 (Runtime): Chrome Helper spawns and downloads 5 MB
        mock_stdout_tick2 = b"Spotify.500,50500,10100,\nGoogle Chrome H.789,5242880,10240,\n"
        with patch.object(collector, "_execute_nettop", return_value=(0, mock_stdout_tick2, b"")):
            deltas = collector.sample()
            delta_dict = {d[1]: (d[0], d[2], d[3]) for d in deltas}
            # Spotify delta should be 500 rx, 100 tx
            self.assertEqual(delta_dict[500], ("Spotify", 500, 100))
            # Chrome Helper (spawned at runtime) MUST be credited with full 5 MB!
            self.assertEqual(delta_dict[789], ("Google Chrome H", 5242880, 10240))


if __name__ == "__main__":
    unittest.main()
