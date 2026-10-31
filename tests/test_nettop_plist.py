#!/usr/bin/env python3
"""
Tests for Plist-based nettop parsing in MacNetLedger.
"""

import plistlib
import unittest
from daemon.macnetledgerd import extract_nettop_processes


class TestNettopPlist(unittest.TestCase):
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
