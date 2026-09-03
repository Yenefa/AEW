"""AEW Hub — shared team coordination layer (MVP).

A two-level system: the Hub owns *only* team coordination state (who owns which
task), while GitHub/AEDL stays the source of truth for repository facts and each
Local AEW keeps its own machine-local `.aew/` state.

Scope is deliberately tiny: SQLite + HTTP, no webhooks, no realtime push, no
multi-team. See `api.py` for the 8 endpoints and `sync.py` for the refresh rules.

This __init__ stays lightweight on purpose: importing `aew.hub` must NOT pull in
the HTTP server or the store. Agent code only needs `TeamTask` / `team_task_to_card`.
"""

from .models import BLOCKED, CLAIMED, DONE, READY, TeamTask, team_task_to_card

__all__ = [
    "READY",
    "CLAIMED",
    "BLOCKED",
    "DONE",
    "TeamTask",
    "team_task_to_card",
]
