"""Tests for persistent project memory (state.py)."""

import tempfile
import unittest
from pathlib import Path

from aew.state import ProjectMemory


class TestProjectMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = ProjectMemory(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_when_empty(self):
        self.assertEqual(self.mem.load_state()["current_phase"], "")
        self.assertEqual(self.mem.load_focus()["unfinished_tasks"], [])
        self.assertEqual(self.mem.load_tasks(), {})

    def test_roundtrip_state(self):
        self.mem.save_state({"current_phase": "P2 Validation"})
        self.assertEqual(self.mem.load_state()["current_phase"], "P2 Validation")

    def test_roundtrip_focus(self):
        self.mem.save_focus({"current_focus": "Evidence", "unfinished_tasks": ["PR-25"]})
        self.assertEqual(self.mem.load_focus()["current_focus"], "Evidence")

    def test_touch_session_sets_today(self):
        self.mem.touch_session()
        self.assertTrue(self.mem.load_focus()["last_session"])

    def test_recovery_summary(self):
        self.mem.save_focus({"current_focus": "Evidence", "unfinished_tasks": ["PR-25"],
                             "last_session": "2026-09-03"})
        self.mem.save_state({"current_phase": "P2"})
        s = self.mem.recovery_summary()
        self.assertIn("Evidence", s)
        self.assertIn("PR-25", s)
        self.assertIn("P2", s)

    def test_corrupt_file_degrades(self):
        (self.mem.dir).mkdir(exist_ok=True)
        (self.mem.dir / "project_state.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.mem.load_state()["current_phase"], "")


if __name__ == "__main__":
    unittest.main()
