"""Tests for the Terminal Agent (v1) — exercised via `handle()`, no TTY needed."""

import tempfile
import unittest
from pathlib import Path

from aew.agent import TerminalAgent

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_project"


class TestTerminalAgent(unittest.TestCase):
    def setUp(self):
        # Use a temp copy so memory writes never touch the committed fixture.
        self.tmp = tempfile.TemporaryDirectory()
        import shutil
        shutil.copytree(SAMPLE, Path(self.tmp.name) / "proj")
        self.agent = TerminalAgent(Path(self.tmp.name) / "proj")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dashboard_has_project(self):
        out = self.agent.dashboard()
        self.assertIn("AEDL-Demo", out)

    def test_tasks_lists_plan(self):
        out = self.agent.handle("tasks")
        self.assertIn("Available tasks", out)

    def test_show_renders_card(self):
        out = self.agent.handle("show 1")
        self.assertIn("task_id", out)
        self.assertIn("difficulty", out)

    def test_dispatch_dry_run(self):
        out = self.agent.handle("dispatch 1")
        self.assertIn("dry-run", out)

    def test_dispatch_api_target(self):
        out = self.agent.handle("dispatch 1 api")
        self.assertIn("API agent", out)

    def test_focus_persists_and_recovers(self):
        self.agent.handle("focus Evidence Validation")
        out = self.agent.handle("recover")
        self.assertIn("Evidence Validation", out)

    def test_quit_returns_sentinel(self):
        self.assertEqual(self.agent.handle("quit"), "__QUIT__")

    def test_unknown_command(self):
        self.assertIn("unknown command", self.agent.handle("frobnicate"))

    def test_recommended_model_assigned(self):
        # difficulty-2 build tasks should route to the cheap tier.
        models = [p.card.recommended_model for p in self.agent.plan]
        self.assertTrue(all(m for m in models), models)


if __name__ == "__main__":
    unittest.main()
