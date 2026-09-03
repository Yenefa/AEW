"""Portable loader integration test against the bundled sample fixture.

The original `test_snapshot.py` runs against the author's private AEDL repo and
is skipped when that path is absent. This test exercises the SAME v0 six-field
acceptance contract on the bundled `examples/sample_project` fixture, plus the
v1 GitHub-aware fields (empty when offline).
"""

import tempfile
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


class TestConventionDiscovery(unittest.TestCase):
    """Discovery is convention-driven, not hard-coded to AEDL's exact paths."""

    def test_design_decisions_from_claude_md(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# Demo\n\n一个演示项目\n", encoding="utf-8")
            (root / "CLAUDE.md").write_text(
                "# Demo\n\n## 设计决策\n\n- 决策一\n- 决策二\n\n## 其他\n\n- 不是决策\n",
                encoding="utf-8",
            )
            snap = load_project(root)
            texts = [d.text for d in snap.decisions]
            self.assertIn("决策一", texts)
            self.assertIn("决策二", texts)
            self.assertNotIn("不是决策", texts)
            self.assertEqual(snap.decisions[0].status, "current")

    def test_task_discovery_by_convention_not_filename(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            docs = root / "docs"
            docs.mkdir()
            (docs / "TODO.md").write_text(
                "| Task | Issue | Description | Status |\n"
                "| --- | --- | --- | --- |\n"
                "| A1 | Issue #1 | do x | OPEN |\n",
                encoding="utf-8",
            )
            snap = load_project(root)
            self.assertEqual({t.task_id for t in snap.tasks}, {"A1"})


class TestDifficultyAndOwner(unittest.TestCase):
    """P0: Owner is never a description; '难度：★★' becomes an explicit difficulty."""

    def test_owner_separate_and_star_difficulty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            docs = root / "docs"
            docs.mkdir()
            (docs / "WAVE4_TASKS.md").write_text(
                "| 任务 | GitHub | 真人 Owner | 当前状态 |\n"
                "| --- | --- | --- | --- |\n"
                "| W4A | Issue #2 | `Yenefa` | claimed |\n"
                "\n"
                "## TASK-W4A：证据冻结（Issue #2）\n"
                "- 难度：★★（取证）\n"
                "- 领地：`docs/`、`src/`\n",
                encoding="utf-8",
            )
            snap = load_project(root)
            w4a = {t.task_id: t for t in snap.tasks}["W4A"]
            self.assertEqual(w4a.owner, "Yenefa")
            self.assertNotIn("Yenefa", w4a.description)
            self.assertEqual(w4a.difficulty, 4)          # ★★ → 4
            self.assertIn("证据冻结", w4a.description)
            self.assertIn("docs/", w4a.assets)

    def test_heading_star_is_owner_type_not_difficulty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            docs = root / "docs"
            docs.mkdir()
            (docs / "TASKS.md").write_text(
                "## TASK-R1：渲染门禁（主线）⭐ 文本 AI\n"
                "### 领地（可写）\n"
                "- `tools/x.py`\n",
                encoding="utf-8",
            )
            snap = load_project(root)
            r1 = {t.task_id: t for t in snap.tasks}["R1"]
            self.assertIsNone(r1.difficulty)             # ⭐ is an owner-type icon, not difficulty
            self.assertEqual(r1.description, "渲染门禁（主线）")
            self.assertIn("tools/x.py", r1.assets)


if __name__ == "__main__":
    unittest.main()
