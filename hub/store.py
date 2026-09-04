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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .models import (
    APPROVED,
    BLOCKED,
    CLAIMED,
    DONE,
    EXECUTING,
    PENDING_HUMAN_REVIEW,
    PROMOTED,
    PROPOSED,
    READY,
    TeamTask,
)

# Coordination states the discovery/upsert layer must NEVER clobber: anything
# past READY/BLOCKED belongs to the run/approval machinery, not the planner.
PROTECTED_STATUSES = frozenset({
    CLAIMED, EXECUTING, PROPOSED, PENDING_HUMAN_REVIEW, APPROVED, PROMOTED, DONE,
})


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
            # v2.1 migration — run ownership / promotion authority. New DBs get the
            # columns via CREATE above when fresh; existing DBs get ALTERs here.
            for col in ("active_run_id TEXT NOT NULL DEFAULT ''",
                        "generation INTEGER NOT NULL DEFAULT 1",
                        "lease_owner TEXT NOT NULL DEFAULT ''",
                        "lease_expires_at TEXT NOT NULL DEFAULT ''",
                        "head_sha TEXT NOT NULL DEFAULT ''"):
                try:
                    conn.execute(f"ALTER TABLE team_tasks ADD COLUMN {col}")
                except sqlite3.OperationalError:
                    pass  # column already exists
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id     TEXT PRIMARY KEY,
                    task_id    TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    worker     TEXT NOT NULL DEFAULT '',
                    base_sha   TEXT NOT NULL DEFAULT '',
                    head_sha   TEXT NOT NULL DEFAULT '',
                    summary    TEXT NOT NULL DEFAULT '',
                    gate_status TEXT NOT NULL DEFAULT '',
                    status     TEXT NOT NULL,   -- ACTIVE / SUPERSEDED / PROPOSED / STALE / COMPLETED
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    schema      TEXT NOT NULL DEFAULT 'human-approval.v1',
                    task_id     TEXT NOT NULL,
                    run_id      TEXT NOT NULL,
                    generation  INTEGER NOT NULL,
                    head_sha    TEXT NOT NULL,
                    decision    TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    approved_at TEXT NOT NULL
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
            active_run_id=r["active_run_id"], generation=r["generation"],
            lease_owner=r["lease_owner"], lease_expires_at=r["lease_expires_at"],
            head_sha=r["head_sha"],
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
            if row["status"] in PROTECTED_STATUSES:
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

    # -- run lease / promotion authority (v2.1) ----------------------------- #
    #
    # One task, one active run. A run is granted by an atomic lease (READY ->
    # EXECUTING with a TTL); every re-assignment bumps the task's generation so
    # stale writers are detectable by (run_id, generation) alone. Workers end at
    # PROPOSED; PENDING_HUMAN_REVIEW -> APPROVED -> PROMOTED is human authority
    # expressed as a receipt bound to (task, run, generation, head_sha).

    def get_run(self, run_id: str) -> Optional[dict]:
        conn = self._conn()
        try:
            r = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def latest_approval(self, task_id: str, run_id: str) -> Optional[dict]:
        conn = self._conn()
        try:
            r = conn.execute(
                "SELECT * FROM approvals WHERE task_id=? AND run_id=? "
                "ORDER BY id DESC LIMIT 1", (task_id, run_id),
            ).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def lease(self, task_id: str, run_id: str, worker: str = "",
              ttl_seconds: int = 3600) -> dict:
        """Atomically grant the single active run for a task (READY -> EXECUTING).

        rowcount 0 = LEASE DENIED (another live run owns it, or task not READY).
        Each granted run takes the next generation number for the task.
        """
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="seconds")
        expires = (now_dt + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
        conn = self._conn()
        try:
            task = conn.execute(
                "SELECT status, active_run_id, lease_expires_at FROM team_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if task is None:
                return {"ok": False, "reason": "task not found"}
            active_live = (
                task["active_run_id"]
                and (task["lease_expires_at"] or "") > now
            )
            if active_live:
                return {"ok": False,
                        "reason": f"lease denied: run {task['active_run_id']} holds it "
                                  f"until {task['lease_expires_at']}"}
            if task["status"] in (APPROVED, PROMOTED, DONE):
                return {"ok": False,
                        "reason": f"lease denied: task is {task['status']} (terminal — "
                                  f"authority states never resurrect via lease expiry)"}
            if task["status"] not in (READY, BLOCKED):
                # expired lease on a non-terminal state: the run is dead, the
                # task may be re-assigned to a fresh run (generation bumps).
                expired = task["active_run_id"] and (task["lease_expires_at"] or "") <= now
                if not expired:
                    return {"ok": False,
                            "reason": f"lease denied: task is {task['status']}, not READY"}
            generation = conn.execute(
                "SELECT COUNT(*) AS n FROM runs WHERE task_id=?", (task_id,)
            ).fetchone()["n"] + 1
            cur = conn.execute(
                "UPDATE team_tasks SET active_run_id=?, lease_owner=?, "
                "lease_expires_at=?, status=?, generation=?, updated_at=? "
                "WHERE task_id=? AND status=? "
                "AND (lease_expires_at='' OR lease_expires_at<=?)",
                (run_id, worker, expires, EXECUTING, generation, now,
                 task_id, task["status"], now),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return {"ok": False, "reason": "lease denied: raced by another writer"}
            conn.execute(
                "INSERT INTO runs (run_id,task_id,generation,worker,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (run_id, task_id, generation, worker, "ACTIVE", now, now),
            )
            conn.execute(
                "UPDATE runs SET status='SUPERSEDED', updated_at=? "
                "WHERE task_id=? AND run_id<>? AND status IN ('ACTIVE','PROPOSED')",
                (now, task_id, run_id),
            )
            conn.execute(
                "INSERT INTO events (ts,kind,task_id,user,detail) VALUES (?,?,?,?,?)",
                (now, "lease", task_id, worker, f"run={run_id} gen={generation}"),
            )
            row = conn.execute(
                "SELECT status, active_run_id, generation, lease_owner, lease_expires_at "
                "FROM team_tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            conn.commit()
            return {"ok": True, "task_id": task_id, "run_id": run_id,
                    "generation": row["generation"], "status": row["status"],
                    "lease_owner": row["lease_owner"],
                    "lease_expires_at": row["lease_expires_at"]}
        finally:
            conn.close()

    def _check_active_run(self, conn, task_id: str, run_id: str) -> Optional[dict]:
        """Shared stale-writer guard. Returns an error dict or None when fresh."""
        task = conn.execute(
            "SELECT status, active_run_id, generation, head_sha FROM team_tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if task is None:
            return {"ok": False, "stale": True, "reason": "task not found"}
        if task["active_run_id"] != run_id:
            return {"ok": False, "stale": True,
                    "reason": f"STALE WRITE DENIED: run {run_id} is not the active run "
                              f"(active={task['active_run_id'] or 'none'}, "
                              f"generation={task['generation']})"}
        run = conn.execute("SELECT generation FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run["generation"] != task["generation"]:
            return {"ok": False, "stale": True,
                    "reason": f"STALE WRITE DENIED: generation mismatch on run {run_id}"}
        return None

    def submit_result(self, task_id: str, run_id: str, summary: str = "",
                      head_sha: str = "", gate_status: str = "") -> dict:
        """Worker hands in a result: EXECUTING -> PROPOSED (agent's ceiling)."""
        now = _now()
        conn = self._conn()
        try:
            err = self._check_active_run(conn, task_id, run_id)
            if err:
                conn.rollback()
                return err
            task = conn.execute(
                "SELECT status, head_sha FROM team_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if task["status"] != EXECUTING:
                conn.rollback()
                return {"ok": False, "stale": True,
                        "reason": f"run {run_id} already {task['status']}"}
            conn.execute(
                "UPDATE runs SET head_sha=?, summary=?, gate_status=?, "
                "status='PROPOSED', updated_at=? WHERE run_id=?",
                (head_sha, summary, gate_status, now, run_id),
            )
            conn.execute(
                "UPDATE team_tasks SET status=?, head_sha=?, updated_at=? WHERE task_id=?",
                (PROPOSED, head_sha, now, task_id),
            )
            conn.execute(
                "INSERT INTO events (ts,kind,task_id,user,detail) VALUES (?,?,?,?,?)",
                (now, "result", task_id, run_id, summary[:120]),
            )
            conn.commit()
            return {"ok": True, "task_id": task_id, "run_id": run_id,
                    "status": PROPOSED, "head_sha": head_sha}
        finally:
            conn.close()

    def request_review(self, task_id: str, run_id: str) -> dict:
        """PROPOSED -> PENDING_HUMAN_REVIEW (still run-checked, still not approval)."""
        now = _now()
        conn = self._conn()
        try:
            err = self._check_active_run(conn, task_id, run_id)
            if err:
                conn.rollback()
                return err
            task = conn.execute(
                "SELECT status FROM team_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if task["status"] != PROPOSED:
                conn.rollback()
                return {"ok": False, "stale": True,
                        "reason": f"cannot request review from {task['status']}"}
            conn.execute(
                "UPDATE team_tasks SET status=?, updated_at=? WHERE task_id=?",
                (PENDING_HUMAN_REVIEW, now, task_id),
            )
            conn.execute(
                "INSERT INTO events (ts,kind,task_id,user,detail) VALUES (?,?,?,?,?)",
                (now, "review", task_id, run_id, ""),
            )
            conn.commit()
            return {"ok": True, "task_id": task_id, "run_id": run_id,
                    "status": PENDING_HUMAN_REVIEW}
        finally:
            conn.close()

    def approve(self, task_id: str, run_id: str, approved_by: str,
                head_sha: str = "") -> dict:
        """HUMAN-ONLY entry (CLI with interactive confirm; never a Hub endpoint).

        PENDING_HUMAN_REVIEW -> APPROVED, producing a receipt bound to
        (task, run, generation, head_sha). Agent-written approval text carries
        no authority; this method is only reachable by whoever runs the Hub CLI.
        """
        now = _now()
        conn = self._conn()
        try:
            err = self._check_active_run(conn, task_id, run_id)
            if err:
                conn.rollback()
                return err
            task = conn.execute(
                "SELECT status, generation, head_sha FROM team_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if task["status"] != PENDING_HUMAN_REVIEW:
                conn.rollback()
                return {"ok": False,
                        "reason": f"cannot approve from {task['status']} "
                                  f"(needs {PENDING_HUMAN_REVIEW})"}
            if head_sha and task["head_sha"] and head_sha != task["head_sha"]:
                conn.rollback()
                return {"ok": False,
                        "reason": f"head binding mismatch: receipt {head_sha[:12]} "
                                  f"vs candidate {task['head_sha'][:12]}"}
            conn.execute(
                "INSERT INTO approvals (schema,task_id,run_id,generation,head_sha,"
                "decision,approved_by,approved_at) "
                "VALUES ('human-approval.v1',?,?,?,?,?,?,?)",
                (task_id, run_id, task["generation"], task["head_sha"],
                 "APPROVED", approved_by, now),
            )
            conn.execute(
                "UPDATE team_tasks SET status=?, updated_at=? WHERE task_id=?",
                (APPROVED, now, task_id),
            )
            conn.execute(
                "UPDATE runs SET status='COMPLETED', updated_at=? WHERE run_id=?",
                (now, run_id),
            )
            conn.execute(
                "INSERT INTO events (ts,kind,task_id,user,detail) VALUES (?,?,?,?,?)",
                (now, "approve", task_id, approved_by, f"run={run_id}"),
            )
            conn.commit()
            receipt = {
                "schema": "human-approval.v1",
                "task": task_id,
                "run_id": run_id,
                "generation": task["generation"],
                "head_sha": task["head_sha"],
                "decision": "APPROVED",
                "approved_by": approved_by,
                "approved_at": now,
            }
            return {"ok": True, "receipt": receipt}
        finally:
            conn.close()

    def promote(self, task_id: str, run_id: str) -> dict:
        """Promotion gate: run -> generation -> head binding -> human receipt.

        Any failed binding denies. Actual git push / merge stays a human action
        outside the Hub; PROMOTED records that authority was properly granted.
        """
        now = _now()
        conn = self._conn()
        try:
            err = self._check_active_run(conn, task_id, run_id)
            if err:
                conn.rollback()
                return err
            task = conn.execute(
                "SELECT status, generation, head_sha FROM team_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if task["status"] != APPROVED:
                conn.rollback()
                return {"ok": False,
                        "reason": f"promotion gate: task is {task['status']}, needs {APPROVED}"}
            receipt = self.latest_approval(task_id, run_id)
            if receipt is None:
                conn.rollback()
                return {"ok": False, "reason": "promotion gate: no human approval receipt"}
            if receipt["generation"] != task["generation"]:
                conn.rollback()
                return {"ok": False,
                        "reason": f"promotion gate: generation mismatch "
                                  f"(receipt {receipt['generation']} vs task {task['generation']})"}
            if (task["head_sha"] or "") and receipt["head_sha"] != task["head_sha"]:
                conn.rollback()
                return {"ok": False,
                        "reason": f"promotion gate: head binding mismatch "
                                  f"(receipt {receipt['head_sha'][:12]} vs "
                                  f"candidate {task['head_sha'][:12]})"}
            conn.execute(
                "UPDATE team_tasks SET status=?, updated_at=? WHERE task_id=?",
                (PROMOTED, now, task_id),
            )
            conn.execute(
                "INSERT INTO events (ts,kind,task_id,user,detail) VALUES (?,?,?,?,?)",
                (now, "promote", task_id, receipt["approved_by"], f"run={run_id}"),
            )
            conn.commit()
            return {"ok": True, "task_id": task_id, "run_id": run_id,
                    "status": PROMOTED, "approved_by": receipt["approved_by"]}
        finally:
            conn.close()
