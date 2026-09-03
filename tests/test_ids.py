"""Tests for stable task IDs (single source of truth shared by planner + hub)."""

import unittest

from aew.ids import project_slug, stable_id


class TestProjectSlug(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(project_slug("AEDL"), "AEDL")

    def test_spaces_and_symbols(self):
        self.assertEqual(project_slug("AEDL-Demo"), "AEDL-DEMO")
        self.assertEqual(project_slug("My Project!"), "MY-PROJECT")

    def test_empty(self):
        self.assertEqual(project_slug(""), "PROJ")


class TestStableId(unittest.TestCase):
    def test_native(self):
        self.assertEqual(stable_id("AEDL", "native", "W4A"), "AEDL-W4A")

    def test_pr(self):
        self.assertEqual(stable_id("AEDL", "pr", "42"), "GH-PR-42")

    def test_issue(self):
        self.assertEqual(stable_id("AEDL", "issue", "37"), "GH-ISSUE-37")

    def test_ci(self):
        self.assertEqual(stable_id("AEDL", "ci", "main"), "GH-CI-main")

    def test_ci_default_ref(self):
        self.assertEqual(stable_id("AEDL", "ci", ""), "GH-CI-default")


if __name__ == "__main__":
    unittest.main()
