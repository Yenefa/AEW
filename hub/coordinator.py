"""Coordinator — thin glue between the store and the HTTP layer.

No business magic here: it composes `Store` (coordination state) with `sync`
(repo discovery) and exposes the small set of operations the Hub API needs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .store import Store
from .sync import refresh


class Coordinator:
    def __init__(self, store: Store, repo: Path | str, github: bool = True):
        self.store = store
        self.repo = Path(repo)
        self.github = github
        self._project = ""

    def refresh(self) -> Dict[str, object]:
        info = refresh(self.store, self.repo, github=self.github)
        self._project = str(info.get("project") or self._project)
        return info

    def snapshot(self) -> Dict[str, object]:
        tasks = self.store.list_tasks()
        counts = {"READY": 0, "CLAIMED": 0, "BLOCKED": 0, "DONE": 0}
        for t in tasks:
            counts[t.status] = counts.get(t.status, 0) + 1
        return {
            "project": self._project,
            "counts": counts,
            "members": self.store.list_members(),
        }

    def tasks(self) -> List[Dict[str, object]]:
        return [t.to_dict() for t in self.store.list_tasks()]

    def mine(self, user: str) -> List[Dict[str, object]]:
        return [t.to_dict() for t in self.store.list_mine(user)]

    def claim(self, task_id: str, user: str) -> Dict[str, object]:
        ok, msg = self.store.claim(task_id, user)
        t = self.store.get_task(task_id)
        return {
            "ok": ok,
            "task_id": task_id,
            "owner": user if ok else (t.owner if t else ""),
            "status": t.status if t else "UNKNOWN",
            "message": msg,
        }

    def release(self, task_id: str, user: str) -> Dict[str, object]:
        ok, msg = self.store.release(task_id, user)
        t = self.store.get_task(task_id)
        return {
            "ok": ok,
            "task_id": task_id,
            "status": t.status if t else "UNKNOWN",
            "message": msg,
        }

    def done(self, task_id: str, user: str) -> Dict[str, object]:
        ok, msg = self.store.done(task_id, user)
        t = self.store.get_task(task_id)
        return {
            "ok": ok,
            "task_id": task_id,
            "status": t.status if t else "UNKNOWN",
            "message": msg,
        }
