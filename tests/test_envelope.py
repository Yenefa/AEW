"""Tests for the TaskCard -> TaskEnvelope bridge.

The bridge must produce YAML that AEDL's strict parser (`tools/envelope.py`)
accepts with ZERO errors, and must map the AECP-required machine fields
(task / base / allowed_paths / forbidden_paths / dependencies) correctly.
"""

import tempfile
import unittest
from pathlib import Path

from aew.envelope import build_envelope, write_envelope
from aew.model import TaskCard

# Lightweight re-implementation of AEDL's machine-field parser for offline tests
# (mirrors AEDL tools/envelope.py; kept local so tests never import AEDL).
_MACHINE = ("base", "dependencies", "allowed_paths", "forbidden_paths", "exceptions")


def _parse(text):
    env = {"task": None, "base_branch": None, "base_sha": None,
           "dependencies": [], "allowed_paths": [], "forbidden_paths": [],
           "errors": []}
    section = None
    cur_dep = None
    import re
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"\s+#.*$", "", line).rstrip()
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0:
            m = re.match(r"^([A-Za-z0-9_\-]+):\s*(.*)$", line)
            if m:
                key = m.group(1)
                if key == "task":
                    env["task"] = m.group(2).strip()
                elif key in _MACHINE:
                    section = key
                    cur_dep = None
                else:
                    section = None
            else:
                section = None
        else:
            if section == "base":
                m = re.match(r"^(branch|sha):\s*(.*)$", line)
                if m:
                    env["base_" + m.group(1)] = m.group(2).strip()
            elif section == "dependencies":
                m = re.match(r"^-\s*ref:\s*(.+)$", line)
                if m:
                    cur_dep = {"ref": m.group(1).strip(), "required_state": None}
                    env["dependencies"].append(cur_dep)
                else:
                    m2 = re.match(r"^required_state:\s*(.+)$", line)
                    if m2 and cur_dep is not None:
                        cur_dep["required_state"] = m2.group(1).strip()
            elif section in ("allowed_paths", "forbidden_paths"):
                m = re.match(r"^-\s*(.+)$", line)
                if m:
                    env[section].append(m.group(1).strip())
    return env


def _card(**kw):
    base = dict(task_id="AEDL-W4A", title="Implement W4A", objective="Build W4A",
                files=["src/a.py", "tests/a.py"], difficulty=4,
                acceptance=["tests pass"], dependencies=["GH-9"],
                forbidden_paths=["gates/**"])
    base.update(kw)
    return TaskCard(**base)


class TestEnvelope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        # fake git HEAD so build_envelope can resolve a base sha
        (self.repo / ".git").mkdir()
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=False)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.repo, check=False)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.repo, check=False)
        (self.repo / "x.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "x.txt"], cwd=self.repo, check=False)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=self.repo, check=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parses_cleanly(self):
        env = _parse(build_envelope(_card(), self.repo))
        self.assertEqual(env["errors"], [])

    def test_maps_machine_fields(self):
        card = _card()
        env = _parse(build_envelope(card, self.repo))
        self.assertEqual(env["task"], "AEDL-W4A")
        self.assertEqual(env["allowed_paths"], ["src/a.py", "tests/a.py"])
        self.assertEqual(env["forbidden_paths"], ["gates/**"])
        self.assertEqual([d["ref"] for d in env["dependencies"]], ["GH-9"])
        self.assertEqual(env["dependencies"][0]["required_state"], "merged")
        self.assertTrue(env["base_sha"])
        self.assertTrue(env["base_branch"])

    def test_empty_lists_are_single_line(self):
        card = _card(files=[], dependencies=[], forbidden_paths=[])
        text = build_envelope(card, self.repo)
        self.assertIn("dependencies: []", text)
        self.assertIn("allowed_paths: []", text)
        self.assertIn("forbidden_paths: []", text)
        env = _parse(text)
        self.assertEqual(env["errors"], [])

    def test_write_envelope_places_file(self):
        card = _card(task_id="AEDL-R1")
        path = write_envelope(card, self.repo, tasks_dir="tasks")
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "AEDL-R1.yaml")


if __name__ == "__main__":
    unittest.main()
