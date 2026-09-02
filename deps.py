"""Parallel-ready — deterministic dependency DAG query.

No AI scheduler. Just a dependency DAG query:

    A  DONE
    B  depends_on A
    C  no dependencies
    D  depends_on B

    READY:     B, C
    PARALLEL:  B + C  (they can run at the same time)

A task is READY only when:
    * it is OPEN (not DONE/CLOSED, not BLOCKED, not CLAIMED), and
    * every dependency is DONE.

BLOCKED is not ready (it is blocked by a ruling, not by a dependency).
CLAIMED is not ready (someone is already on it).
"""

from __future__ import annotations

from typing import List, Tuple

from .model import Task

TERMINAL = {"DONE", "CLOSED"}
READY_STATES = {"OPEN"}          # only OPEN is "ready to pick up"


def parallel_ready(tasks: List[Task]) -> Tuple[List[str], List[str]]:
    """Return (ready_ids, blocked_by_deps_ids)."""
    status = {t.task_id: t.status.upper() for t in tasks}
    ready: List[str] = []
    blocked: List[str] = []

    for t in tasks:
        st = status[t.task_id]
        if st in TERMINAL:
            continue
        unmet = [d for d in t.dependencies if status.get(d, "UNKNOWN") not in TERMINAL]
        if unmet:
            blocked.append(t.task_id)
        elif st in READY_STATES:
            ready.append(t.task_id)
        # else: BLOCKED / CLAIMED / UNKNOWN -> neither ready nor dep-blocked

    return ready, blocked
