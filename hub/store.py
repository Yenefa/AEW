"""SQLite store — the single source of truth for *team coordination* state.

Three tables only (team_tasks / members / events), exactly as scoped. The store's
hard rule: `upsert` never overwrites CLAIMED / DONE ownership — the planner only
*discovers* candidate tasks; the store *remembers* what the team already did with
them. That is what stops "refresh resurrects a task the team already claimed".

Atomicity: `claim` is a single `UPDATE ... WHERE status='READY'` guarded by
`rowcount`. SQLite serializes writers, so two clients racing for the same READY
task can never both succeed.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .models import CLAIMED, DONE, READY, TeamTask


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path | str):
        self.path = str(db_path)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS team_tasks (
                    task_id           TEXT PRIMARY KEY,
                    title             TEXT NOT NULL,
                    source            TEXT NOT NULL,
                    status            TEXT NOT NULL,
                    owner             TEXT NOT NULL DEFAULT '',
                    difficulty        INTEGER NOT NULL DEFAULT 0,
                    recommended_model TEXT NOT NULL DEFAULT '',
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS members (
                    name       TEXT PRIMARY KEY,
                    last_seen  TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts      TEXT NOT NULL,
                    kind    TEXT NOT NULL,
                    task_id TEXT NOT NULL DEFAULT '',
                    user    TEXT NOT NULL DEFAULT '',
                    detail  TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    # -- read -------------------------------------------------------------- #

    @staticmethod
    def _from_row(r: sqlite3.Row) -> TeamTask:
        return TeamTask(
            task_id=r["task_id"], title=r["title"], source=r["source"],
            status=r["status"], owner=r["owner"], difficulty=r["difficulty"],
            recommended_model=r["recommended_model"],
            created_at=r["created_at"], updated_at=r["updated_at"],
        )

    def list_tasks(self) -> List[TeamTask]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM team_tasks ORDER BY created_at").fetchall()
            return [self._from_row(r) for r in rows]
        finally:
            conn.close()

    def get_task(self, task_id: str) -> Optional[TeamTask]:
        conn = self._conn()
        try:
            r = conn.execute("SELECT * FROM team_tasks WHERE task_id=?", (task_id,)).fetchone()
            return self._from_row(r) if r else None
        finally:
            conn.close()

    def list_mine(self, user: str) -> List[TeamTask]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM team_tasks WHERE owner=? AND status=? ORDER BY updated_at",
                (user, CLAIMED),
            ).fetchall()
            return [self._from_row(r) for r in rows]
        finally:
            conn.close()

    def list_members(self) -> List[str]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT name FROM members ORDER BY last_seen DESC").fetchall()
            return [r["name"] for r in rows]
        finally:
            conn.close()

    # -- upsert (discovery; never clobbers team state) ---------------------- #

    def upsert(self, tt: TeamTask) -> bool:
        """Insert a newly discovered candidate; refresh metadata only for
        READY/BLOCKED rows. CLAIMED/DONE are the team's call and are left alone.

        Returns True when a new row was inserted, False otherwise.
        """
        now = _now()
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT status FROM team_tasks WHERE task_id=?", (tt.task_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO team_tasks "
                    "(task_id,title,source,status,owner,difficulty,recommended_model,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (tt.task_id, tt.title, tt.source, tt.status, "",
                     tt.difficulty, tt.recommended_model, now, now),
                )
                conn.commit()
                return True
            if row["status"] in (CLAIMED, DONE):
                return False
            # READY/BLOCKED: refresh the derived facts, keep coordination state.
            conn.execute(
                "UPDATE team_tasks SET title=?, source=?, status=?, difficulty=?, "
                "recommended_model=?, updated_at=? WHERE task_id=?",
                (tt.title, tt.source, tt.status, tt.difficulty,
                 tt.recommended_model, now, tt.task_id),
            )
            conn.commit()
            return False
        finally:
            conn.close()

    # -- claim / release / done (atomic) ----------------------------------- #

    def claim(self, task_id: str, user: str) -> Tuple[bool, str]:
        """Atomically claim a READY task. Returns (ok, message)."""
        now = _now()
        conn = self._conn()
        try:
            cur = conn.execute(
                "UPDATE team_tasks SET owner=?, status=?, updated_at=? "
                "WHERE task_id=? AND status=?",
                (user, CLAIMED, now, task_id, READY),
            )
            if cur.rowcount == 0:
                row = conn.execute(
                    "SELECT owner,status FROM team_tasks WHERE task_id=?", (task_id,)
                ).fetchone()
                conn.rollback()
                if row is None:
                    return False, "task not found"
                who = row["owner"] or "(none)"
                return False, f"already {row['status']} by {who}"
            conn.execute(
                "INSERT INTO events (ts,kind,task_id,user,detail) VALUES (?,?,?,?,?)",
                (now, "claim", task_id, user, ""),
            )
            conn.execute(
                "INSERT INTO members (name,last_seen) VALUES (?,?) "
                "ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen",
                (user, now),
            )
            conn.commit()
            return True, "claimed"
        finally:
            conn.close()

    def release(self, task_id: str, user: str) -> Tuple[bool, str]:
        now = _now()
        conn = self._conn()
        try:
            cur = conn.execute(
                "UPDATE team_tasks SET owner='', status=?, updated_at=? "
                "WHERE task_id=? AND owner=? AND status=?",
                (READY, now, task_id, user, CLAIMED),
            )
            if cur.rowcount == 0:
                row = conn.execute(
                    "SELECT owner,status FROM team_tasks WHERE task_id=?", (task_id,)
                ).fetchone()
                conn.rollback()
                if row is None:
                    return False, "task not found"
                return False, f"cannot release: {row['status']} by {row['owner'] or '(none)'}"
            conn.execute(
                "INSERT INTO events (ts,kind,task_id,user,detail) VALUES (?,?,?,?,?)",
                (now, "release", task_id, user, ""),
            )
            conn.commit()
            return True, "released"
        finally:
            conn.close()

    def done(self, task_id: str, user: str) -> Tuple[bool, str]:
        now = _now()
        conn = self._conn()
        try:
            cur = conn.execute(
                "UPDATE team_tasks SET status=?, updated_at=? "
                "WHERE task_id=? AND owner=? AND status=?",
                (DONE, now, task_id, user, CLAIMED),
            )
            if cur.rowcount == 0:
                row = conn.execute(
                    "SELECT owner,status FROM team_tasks WHERE task_id=?", (task_id,)
                ).fetchone()
                conn.rollback()
                if row is None:
                    return False, "task not found"
                return False, f"cannot mark done: {row['status']} by {row['owner'] or '(none)'}"
            conn.execute(
                "INSERT INTO events (ts,kind,task_id,user,detail) VALUES (?,?,?,?,?)",
                (now, "done", task_id, user, ""),
            )
            conn.commit()
            return True, "done"
        finally:
            conn.close()
