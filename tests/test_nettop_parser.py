#!/usr/bin/env python3
"""
Unit tests for NetTopParser in MacNetLedger.
"""

import unittest
from daemon.macnetledgerd import NetTopParser


class TestNetTopParser(unittest.TestCase):
    def test_parse_standard_nettop_csv(self):
        line = "14:20:01.120,Google Chrome.4120,45210,1200,en0"
        parsed = NetTopParser.parse_line(line)
        self.assertIsNotNone(parsed)
        comm, pid, rx, tx, iface = parsed
        self.assertEqual(comm, "Google Chrome")
        self.assertEqual(pid, 4120)
        self.assertEqual(rx, 45210)
        self.assertEqual(tx, 1200)
        self.assertEqual(iface, "en0")

    def test_parse_system_daemon_with_dots_in_name(self):
        # Example: com.apple.WebKit.Networking.582
        line = "14:20:01.125,com.apple.WebKit.Networking.582,120400,8540,en0"
        parsed = NetTopParser.parse_line(line)
        self.assertIsNotNone(parsed)
        comm, pid, rx, tx, iface = parsed
        self.assertEqual(comm, "com.apple.WebKit.Networking")
        self.assertEqual(pid, 582)
        self.assertEqual(rx, 120400)
        self.assertEqual(tx, 8540)
        self.assertEqual(iface, "en0")

    def test_parse_without_explicit_interface(self):
        line = "14:20:01.128,nsurlsessiond.418,98000,12000"
        parsed = NetTopParser.parse_line(line)
        self.assertIsNotNone(parsed)
        comm, pid, rx, tx, iface = parsed
        self.assertEqual(comm, "nsurlsessiond")
        self.assertEqual(pid, 418)
        self.assertEqual(rx, 98000)
        self.assertEqual(tx, 12000)
        self.assertEqual(iface, "en0")  # default fallback

    def test_parse_headers_and_invalid_lines(self):
        self.assertIsNone(NetTopParser.parse_line(""))
        self.assertIsNone(NetTopParser.parse_line("   "))
        self.assertIsNone(NetTopParser.parse_line("time,process,bytes_in,bytes_out"))
        self.assertIsNone(NetTopParser.parse_line("bytes_in,bytes_out"))
        self.assertIsNone(NetTopParser.parse_line("=== Sample 1 ==="))
        self.assertIsNone(NetTopParser.parse_line("invalid,data,here"))
        self.assertIsNone(NetTopParser.parse_line("14:20:01,invalid_no_pid,100,200"))


if __name__ == "__main__":
    unittest.main()
