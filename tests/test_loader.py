"""Portable loader integration test against the bundled sample fixture.

The original `test_snapshot.py` runs against the author's private AEDL repo and
is skipped when that path is absent. This test exercises the SAME v0 six-field
acceptance contract on the bundled `examples/sample_project` fixture, plus the
v1 GitHub-aware fields (empty when offline).
"""

import unittest
from pathlib import Path

from aew.loaders.aedl import load_project

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_project"


class TestSampleLoader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = load_project(SAMPLE, github=True)

    def test_identity(self):
        self.assertEqual(self.snap.project.name, "AEDL-Demo")
        self.assertIn("Autonomous", self.snap.project.tagline)

    def test_tasks(self):
        ids = {t.task_id: t.status for t in self.snap.tasks}
        self.assertIn("W4A", ids)
        self.assertEqual(ids.get("W4B"), "CLAIMED")
        self.assertIn("Sandbox-V3", ids)

    def test_decisions(self):
        active = {d.decision_id for d in self.snap.decisions if d.status == "current"}
        self.assertIn("ADR-002", active)
        self.assertNotIn("ADR-001", active)   # superseded
        self.assertNotIn("ADR-009", active)   # proposed

    def test_parallel_ready(self):
        self.assertIn("W4A", self.snap.parallel_ready)
        self.assertIn("W4C", self.snap.parallel_ready)
        self.assertNotIn("W4B", self.snap.parallel_ready)   # CLAIMED

    def test_assets(self):
        by_id = {t.task_id: t for t in self.snap.tasks}
        self.assertTrue(by_id["W4A"].assets)
        self.assertIn("src/hardware/edd001-board/evidence/", by_id["W4A"].assets)

    def test_render(self):
        out = self.snap.render()
        self.assertIn("AEW PROJECT SNAPSHOT", out)
        self.assertIn("AEDL-Demo", out)

    def test_github_fields_present_but_empty_offline(self):
        # Fields exist and default safely; GitHub data is empty without `gh`.
        self.assertEqual(self.snap.pull_requests, [])
        self.assertEqual(self.snap.issues, [])
        self.assertEqual(self.snap.ci.state, "unknown")


if __name__ == "__main__":
    unittest.main()
