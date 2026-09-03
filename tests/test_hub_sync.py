"""Tests for the Hub sync — stable IDs + refresh preserving coordination state."""

import tempfile
import unittest
from pathlib import Path

from aew.hub.models import CLAIMED, READY, BLOCKED, TeamTask
from aew.hub.store import Store
from aew.hub.sync import _stable_id, derive_candidates, refresh
from aew.model import (
    CIStatus,
    Issue,
    ProjectIdentity,
    ProjectSnapshot,
    PullRequest,
    Task,
)


class TestStableId(unittest.TestCase):
    def test_ids(self):
        self.assertEqual(_stable_id("AEDL", "native", "W4A"), "AEDL-W4A")
        self.assertEqual(_stable_id("AEDL", "pr", "42"), "GH-PR-42")
        self.assertEqual(_stable_id("AEDL", "issue", "37"), "GH-ISSUE-37")
        self.assertEqual(_stable_id("AEDL", "ci", "main"), "GH-CI-main")

    def test_ci_default_ref(self):
        self.assertEqual(_stable_id("AEDL", "ci", ""), "GH-CI-default")


def _snap(**overrides):
    base = ProjectSnapshot(
        project=ProjectIdentity(name="AEDL"),
        tasks=[Task(task_id="W4A", status="OPEN"),
               Task(task_id="W4B", status="OPEN", dependencies=["W4A"]),
               Task(task_id="W4C", status="DONE")],
        parallel_ready=["W4A"],
        blocked_by_deps=["W4B"],
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


class TestDerive(unittest.TestCase):
    def test_native_ready_and_blocked(self):
        cands = derive_candidates(_snap())
        by_id = {c.task_id: c for c in cands}
        self.assertEqual(by_id["AEDL-W4A"].status, READY)
        self.assertEqual(by_id["AEDL-W4B"].status, BLOCKED)
        self.assertNotIn("AEDL-W4C", by_id)  # DONE belongs to the store, not derive

    def test_pr_and_issue_and_ci(self):
        snap = _snap(
            pull_requests=[PullRequest(number=42, title="x", state="open",
                                       review_status="REVIEW_REQUIRED")],
            issues=[Issue(number=37, title="flaky", state="open")],
            ci=CIStatus(ref="main", state="failure", conclusion="failure"),
        )
        by_id = {c.task_id: c for c in derive_candidates(snap)}
        self.assertIn("GH-PR-42", by_id)
        self.assertIn("GH-ISSUE-37", by_id)
        self.assertIn("GH-CI-main", by_id)
        self.assertEqual(by_id["GH-PR-42"].source, "pr")

    def test_skip_draft_pr(self):
        snap = _snap(pull_requests=[PullRequest(number=1, title="x", state="open",
                                                draft=True, review_status="")])
        by_id = {c.task_id: c for c in derive_candidates(snap)}
        self.assertNotIn("GH-PR-1", by_id)


class TestRefresh(unittest.TestCase):
    def test_refresh_does_not_clobber_claimed(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            store = Store(Path(tmp.name) / "db.sqlite")
            store.upsert(TeamTask(task_id="AEDL-W4A", title="Implement W4A",
                                  source="native", status=READY))
            store.claim("AEDL-W4A", "Maple")
            repo = Path(tmp.name) / "repo"
            repo.mkdir()
            info = refresh(store, repo, github=False)
            self.assertIn("total", info)
            t = store.get_task("AEDL-W4A")
            self.assertEqual(t.status, CLAIMED)
            self.assertEqual(t.owner, "Maple")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
