"""Tests for the Hub SQLite store — the coordination-state source of truth.

The two invariants that matter most:
  1. `upsert` must never overwrite CLAIMED/DONE (refresh must not resurrect).
  2. `claim` is atomic — concurrent claims of the same READY task yield one winner.
"""

import tempfile
import threading
import unittest
from pathlib import Path

from aew.hub.models import BLOCKED, CLAIMED, DONE, READY, TeamTask
from aew.hub.store import Store


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "hub.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_inserts_new(self):
        tt = TeamTask(task_id="AEDL-W4A", title="Implement W4A", source="native", status=READY)
        self.assertTrue(self.store.upsert(tt))
        self.assertEqual(self.store.get_task("AEDL-W4A").status, READY)

    def test_upsert_does_not_clobber_claimed(self):
        self.store.upsert(TeamTask(task_id="AEDL-W4A", title="x", source="native", status=READY))
        self.assertTrue(self.store.claim("AEDL-W4A", "Maple")[0])
        # Planner rediscovers it as READY on the next refresh.
        self.store.upsert(TeamTask(task_id="AEDL-W4A", title="x", source="native", status=READY))
        t = self.store.get_task("AEDL-W4A")
        self.assertEqual(t.status, CLAIMED)
        self.assertEqual(t.owner, "Maple")

    def test_upsert_does_not_clobber_done(self):
        self.store.upsert(TeamTask(task_id="T1", title="x", source="native", status=READY))
        self.store.claim("T1", "Maple")
        self.store.done("T1", "Maple")
        self.store.upsert(TeamTask(task_id="T1", title="x", source="native", status=READY))
        self.assertEqual(self.store.get_task("T1").status, DONE)

    def test_upsert_refreshes_ready_metadata(self):
        self.store.upsert(TeamTask(task_id="T1", title="old", source="native",
                                   status=READY, difficulty=1))
        self.store.upsert(TeamTask(task_id="T1", title="new", source="native",
                                   status=BLOCKED, difficulty=5))
        t = self.store.get_task("T1")
        self.assertEqual(t.status, BLOCKED)
        self.assertEqual(t.difficulty, 5)
        self.assertEqual(t.title, "new")

    def test_claim_atomic_concurrent(self):
        self.store.upsert(TeamTask(task_id="T1", title="x", source="native", status=READY))
        results = []

        def worker(name):
            results.append((name, self.store.claim("T1", name)[0]))

        threads = [threading.Thread(target=worker, args=(f"u{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(1 for _, ok in results if ok), 1)

    def test_claim_already_claimed_fails(self):
        self.store.upsert(TeamTask(task_id="T1", title="x", source="native", status=READY))
        self.assertTrue(self.store.claim("T1", "A")[0])
        ok, msg = self.store.claim("T1", "B")
        self.assertFalse(ok)
        self.assertIn("already", msg)

    def test_claim_missing_task(self):
        ok, msg = self.store.claim("NOPE", "A")
        self.assertFalse(ok)
        self.assertIn("not found", msg)

    def test_release_and_done_roundtrip(self):
        self.store.upsert(TeamTask(task_id="T1", title="x", source="native", status=READY))
        self.store.claim("T1", "A")
        self.assertTrue(self.store.release("T1", "A")[0])
        self.assertEqual(self.store.get_task("T1").status, READY)
        self.store.claim("T1", "A")
        self.assertTrue(self.store.done("T1", "A")[0])
        self.assertEqual(self.store.get_task("T1").status, DONE)

    def test_release_by_other_fails(self):
        self.store.upsert(TeamTask(task_id="T1", title="x", source="native", status=READY))
        self.store.claim("T1", "A")
        self.assertFalse(self.store.release("T1", "B")[0])
        self.assertFalse(self.store.done("T1", "B")[0])

    def test_list_mine(self):
        self.store.upsert(TeamTask(task_id="T1", title="x", source="native", status=READY))
        self.store.claim("T1", "Maple")
        mine = self.store.list_mine("Maple")
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].task_id, "T1")
        self.assertEqual(self.store.list_mine("Ryan"), [])

    def test_members_recorded_on_claim(self):
        self.store.upsert(TeamTask(task_id="T1", title="x", source="native", status=READY))
        self.store.claim("T1", "Maple")
        self.assertIn("Maple", self.store.list_members())


if __name__ == "__main__":
    unittest.main()
