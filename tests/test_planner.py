"""Tests for the Task Planner + Difficulty Rating (v1).

Deterministic: given an explicit snapshot, `plan()` must derive the same triaged
task list every time, in priority order (CI > review > resume > build > triage).
"""

import unittest

from aew.model import (
    CIStatus,
    Issue,
    ProjectIdentity,
    ProjectSnapshot,
    PullRequest,
    Task,
)
from aew.planner import difficulty_band, plan, rate_difficulty


class TestDifficultyRating(unittest.TestCase):
    def test_trivial_task_is_zero(self):
        self.assertEqual(rate_difficulty(), 0)

    def test_each_factor_adds(self):
        self.assertEqual(rate_difficulty(files_count=6), 1)
        self.assertEqual(rate_difficulty(cross_module=True), 2)
        self.assertEqual(rate_difficulty(architecture=True), 3)
        self.assertEqual(rate_difficulty(hardware=True), 2)
        self.assertEqual(rate_difficulty(needs_verification=True), 1)
        self.assertEqual(rate_difficulty(security=True), 2)

    def test_caps_at_ten(self):
        score = rate_difficulty(
            files_count=9, cross_module=True, architecture=True,
            hardware=True, needs_verification=True, security=True,
        )
        self.assertEqual(score, 10)

    def test_band_mapping(self):
        self.assertEqual(difficulty_band(0), "simple")
        self.assertEqual(difficulty_band(3), "simple")
        self.assertEqual(difficulty_band(4), "standard")
        self.assertEqual(difficulty_band(7), "standard")
        self.assertEqual(difficulty_band(8), "architectural")
        self.assertEqual(difficulty_band(10), "architectural")


def _snapshot(**overrides):
    base = ProjectSnapshot(
        project=ProjectIdentity(name="AEDL", tagline="test"),
        tasks=[
            Task(task_id="W4A", status="OPEN", assets=["src/evidence/"]),
            Task(task_id="W4B", status="CLAIMED"),
            Task(task_id="W4C", status="OPEN"),
        ],
        parallel_ready=["W4A", "W4C"],
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


class TestPlanner(unittest.TestCase):
    def test_ci_failure_is_first_and_high(self):
        snap = _snapshot(ci=CIStatus(ref="main", state="failure", conclusion="failure"))
        pts = plan(snap)
        self.assertTrue(pts)
        self.assertEqual(pts[0].priority, "High")
        self.assertIn("CI", pts[0].card.title)

    def test_pr_review_generated(self):
        snap = _snapshot(pull_requests=[
            PullRequest(number=25, title="add evidence validator",
                        review_status="REVIEW_REQUIRED"),
        ])
        pts = plan(snap)
        titles = [p.card.title for p in pts]
        self.assertTrue(any("PR #25" in t for t in titles))

    def test_changed_requests_is_high_priority(self):
        snap = _snapshot(pull_requests=[
            PullRequest(number=25, title="x", review_status="CHANGES_REQUESTED"),
        ])
        pts = plan(snap)
        pr = next(p for p in pts if "PR #25" in p.card.title)
        self.assertEqual(pr.priority, "High")

    def test_parallel_ready_becomes_build_task(self):
        snap = _snapshot()
        pts = plan(snap)
        titles = [p.card.title for p in pts]
        self.assertTrue(any("W4A" in t for t in titles))

    def test_claimed_not_planned(self):
        snap = _snapshot()
        pts = plan(snap)
        titles = " ".join(p.card.title for p in pts)
        self.assertNotIn("W4B", titles)

    def test_open_issue_becomes_triage(self):
        snap = _snapshot(issues=[Issue(number=7, title="flaky test", state="open")])
        pts = plan(snap)
        self.assertTrue(any("issue #7" in p.card.title for p in pts))

    def test_unfinished_focus_resurfaced(self):
        snap = _snapshot()
        pts = plan(snap, focus={"unfinished_tasks": ["PR-25 review"]})
        self.assertTrue(any("PR-25 review" in p.card.title for p in pts))

    def test_task_ids_are_unique(self):
        snap = _snapshot(pull_requests=[PullRequest(number=1, title="a")],
                         issues=[Issue(number=2, title="b")])
        ids = [p.card.task_id for p in plan(snap)]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
