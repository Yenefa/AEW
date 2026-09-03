"""Persistent project memory — the antidote to "session 失忆".

The Terminal Agent does NOT persist chat transcripts, and — just as important —
it does NOT persist *derived* project state. PR status, issue status, CI status,
task counts and completion % are all live facts re-read from the repo + GitHub on
every startup (loaders/aedl.py + github.py). Caching them here would fork a
second, stale source of truth.

`.aew/` stores only the small, high-signal context that cannot be re-derived
from the repo — the decision layer's own annotations:

    .aew/project_state.json   — the agent's annotation: current phase
    .aew/active_tasks.json    — tasks currently dispatched (in flight)
    .aew/focus.json           — current focus + unfinished threads + last session

Everything is JSON in a `.aew/` directory inside the repo, so it travels with the
project (committed or gitignored, the team's call). Read/write is idempotent and
never raises: a missing file is an empty dict, a corrupt file is skipped.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict


class ProjectMemory:
    """Read/write the three persistent JSON files under `<repo>/.aew/`."""

    def __init__(self, repo: Path | str):
        self.repo = Path(repo)
        self.dir = self.repo / ".aew"

    # -- low-level JSON ---------------------------------------------------- #

    def _read_json(self, name: str, default: dict) -> dict:
        path = self.dir / name
        if not path.exists():
            return dict(default)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else dict(default)
        except Exception:
            return dict(default)

    def _write_json(self, name: str, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -- project state ----------------------------------------------------- #

    def load_state(self) -> dict:
        # Only the agent's own annotation. Derived counters (open_tasks, blocked,
        # pending_pr, completion) are NOT persisted — they are re-computed from
        # the live snapshot / GitHub on every startup.
        return self._read_json("project_state.json", {
            "current_phase": "",
        })

    def save_state(self, state: dict) -> None:
        self._write_json("project_state.json", state)

    # -- active tasks ------------------------------------------------------ #

    def load_tasks(self) -> dict:
        return self._read_json("active_tasks.json", {})

    def save_tasks(self, tasks: dict) -> None:
        self._write_json("active_tasks.json", tasks)

    # -- focus ------------------------------------------------------------- #

    def load_focus(self) -> dict:
        return self._read_json("focus.json", {
            "current_focus": "",
            "last_session": "",
            "unfinished_tasks": [],
        })

    def save_focus(self, focus: dict) -> None:
        self._write_json("focus.json", focus)

    # -- conveniences ------------------------------------------------------ #

    def touch_session(self) -> None:
        """Record that a session happened today (kept in focus.last_session)."""
        today = date.today().isoformat()
        focus = self.load_focus()
        focus["last_session"] = today
        self.save_focus(focus)

    def recovery_summary(self) -> str:
        """One-line recap of what the previous session left behind."""
        focus = self.load_focus()
        state = self.load_state()
        parts = []
        if focus.get("current_focus"):
            parts.append(f"focus: {focus['current_focus']}")
        if focus.get("unfinished_tasks"):
            parts.append("unfinished: " + ", ".join(focus["unfinished_tasks"]))
        if state.get("current_phase"):
            parts.append(f"phase: {state['current_phase']}")
        if focus.get("last_session"):
            parts.append(f"last session: {focus['last_session']}")
        return " · ".join(parts) if parts else "(no prior session)"
