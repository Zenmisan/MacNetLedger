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


if __name__ == "__main__":
    unittest.main()
