"""Tests for AEW v0 — the six-part acceptance + deterministic DAG.

Acceptance (from the v0 scope contract): give AEW a real project, with no
human explanation, and it must correctly output the six fields.
"""

import unittest
from pathlib import Path

from aew.deps import parallel_ready
from aew.model import ProjectSnapshot, Task
from aew.loaders.aedl import load_project

AEDL = Path(r"C:/Users/fuker/Desktop/workspace/aedl")


class TestParallelReady(unittest.TestCase):
    def test_deterministic_dag(self):
        """A DONE; B depends A; C none; D depends B -> READY: B, C."""
        tasks = [
            Task(task_id="A", status="DONE"),
            Task(task_id="B", dependencies=["A"]),
            Task(task_id="C"),
            Task(task_id="D", dependencies=["B"]),
        ]
        ready, blocked = parallel_ready(tasks)
        self.assertEqual(ready, ["B", "C"])
        self.assertEqual(blocked, ["D"])

    def test_all_done_not_ready(self):
        tasks = [Task(task_id="A", status="DONE")]
        ready, blocked = parallel_ready(tasks)
        self.assertEqual(ready, [])
        self.assertEqual(blocked, [])


class TestAedlSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = load_project(AEDL)

    def test_identity(self):
        self.assertEqual(self.snap.project.name, "AEDL")
        self.assertIn("Autonomous", self.snap.project.tagline)

    def test_tasks(self):
        ids = {t.task_id: t.status for t in self.snap.tasks}
        self.assertIn("W4A", ids)
        self.assertIn("W4C", ids)
        self.assertEqual(ids.get("W4B"), "CLAIMED")

    def test_decisions(self):
        self.assertTrue(self.snap.decisions)
        self.assertTrue(any(d.decision_id.startswith("ADR-") for d in self.snap.decisions))

    def test_events(self):
        self.assertTrue(self.snap.events)

    def test_parallel_ready_present(self):
        self.assertTrue(self.snap.parallel_ready)

    def test_claimed_not_in_ready(self):
        """W4B is CLAIMED — it must NOT appear in parallel-ready."""
        self.assertNotIn("W4B", self.snap.parallel_ready)

    def test_open_tasks_are_ready(self):
        """W4A / W4C / Sandbox-V3 are OPEN -> ready."""
        self.assertIn("W4A", self.snap.parallel_ready)
        self.assertIn("W4C", self.snap.parallel_ready)
        self.assertIn("Sandbox-V3", self.snap.parallel_ready)

    def test_decisions_exclude_superseded_and_proposed(self):
        """Superseded (ADR-001) and Proposed (ADR-009/010) must not be active."""
        active = {d.decision_id for d in self.snap.decisions if d.status == "current"}
        self.assertNotIn("ADR-001", active)   # superseded by ADR-002
        self.assertNotIn("ADR-009", active)   # proposed
        self.assertNotIn("ADR-010", active)   # proposed
        self.assertIn("ADR-002", active)      # accepted

    def test_task_discovery_not_hardcoded(self):
        """Tasks are discovered structurally, not by hard-coded IDs."""
        ids = {t.task_id for t in self.snap.tasks}
        self.assertIn("W4A", ids)
        self.assertIn("Sandbox-V3", ids)

    def test_render(self):
        out = self.snap.render()
        self.assertIn("AEW PROJECT SNAPSHOT", out)
        self.assertIn("AEDL", out)
        self.assertIn("Parallel-ready", out)


if __name__ == "__main__":
    unittest.main()
