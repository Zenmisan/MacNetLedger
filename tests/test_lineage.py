#!/usr/bin/env python3
"""
Unit tests for DarwinProcessResolver in MacNetLedger.
"""

import unittest
from unittest.mock import patch
from daemon.macnetledgerd import DarwinProcessResolver, LINEAGE_CACHE


class TestDarwinProcessResolver(unittest.TestCase):
    def setUp(self):
        LINEAGE_CACHE.clear()
        self.resolver = DarwinProcessResolver()

    def test_system_daemon_resolution(self):
        group, cat, child_comm, detail = self.resolver.resolve(101, "nsurlsessiond")
        self.assertEqual(group, "Apple Background Transfers")
        self.assertEqual(cat, "system")
        self.assertEqual(child_comm, "nsurlsessiond")

        group, cat, child_comm, detail = self.resolver.resolve(102, "cloudd")
        self.assertEqual(group, "iCloud Drive Sync")
        self.assertEqual(cat, "system")

    def test_cli_tools_resolution(self):
        group, cat, child_comm, detail = self.resolver.resolve(201, "curl")
        self.assertEqual(group, "cURL")
        self.assertEqual(cat, "cli")

        group, cat, child_comm, detail = self.resolver.resolve(202, "git")
        self.assertEqual(group, "Git")
        self.assertEqual(cat, "cli")

    def test_app_bundle_resolution_via_path(self):
        mock_path = "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/114/Helpers/Google Chrome Helper (Renderer).app/Contents/MacOS/Google Chrome Helper (Renderer)"

        with patch.object(self.resolver, "get_process_path", return_value=mock_path):
            group, cat, child_comm, detail = self.resolver.resolve(301, "Google Chrome Helper (Renderer)")
            self.assertEqual(group, "Google Chrome")
            self.assertEqual(cat, "browser")
            self.assertEqual(child_comm, "Google Chrome Helper (Renderer)")

    def test_third_party_app_bundle_resolution(self):
        mock_path = "/Applications/Slack.app/Contents/MacOS/Slack"

        with patch.object(self.resolver, "get_process_path", return_value=mock_path):
            group, cat, child_comm, detail = self.resolver.resolve(401, "Slack")
            self.assertEqual(group, "Slack")
            self.assertEqual(cat, "app")

    def test_cache_utilization(self):
        self.resolver.resolve(501, "curl")
        self.assertIn(501, LINEAGE_CACHE)

        # Subsequent call should return cached tuple immediately
        cached_result = self.resolver.resolve(501, "curl")
        self.assertEqual(cached_result[0], "cURL")


if __name__ == "__main__":
    unittest.main()
