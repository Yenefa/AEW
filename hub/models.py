"""Hub data model — a TeamTask is the shared, stable unit of coordination.

Team task IDs must be STABLE across refreshes (unlike the planner's
`PROJECT-YYYYMMDD-NNN`), otherwise the store would duplicate tasks on every
refresh. Stable identities:

    native task   -> {PROJECT}-{task_id}   e.g. AEDL-W4A
    PR            -> GH-PR-{number}        e.g. GH-PR-42
    issue         -> GH-ISSUE-{number}     e.g. GH-ISSUE-37
    CI            -> GH-CI-{ref}           e.g. GH-CI-main
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict

from ..model import TaskCard

READY = "READY"
CLAIMED = "CLAIMED"
BLOCKED = "BLOCKED"
DONE = "DONE"

STATES = (READY, CLAIMED, BLOCKED, DONE)


@dataclass
class TeamTask:
    task_id: str
    title: str
    source: str                 # native / pr / issue / ci
    status: str = READY
    owner: str = ""
    difficulty: int = 0
    recommended_model: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def team_task_to_card(tt: TeamTask) -> TaskCard:
    """Convert a claimed team task into a local TaskCard for planner/router/dispatch."""
    return TaskCard(
        task_id=tt.task_id,
        title=tt.title,
        objective=tt.title,
        project=_project_hint(tt.task_id, tt.source),
        current_stage="",
        constraints=[],
        files=[],
        difficulty=tt.difficulty,
        recommended_model=tt.recommended_model,
        acceptance=["return a RESULT CARD", f"mark {tt.task_id} DONE on the hub"],
    )


def _project_hint(task_id: str, source: str) -> str:
    if source == "native":
        return task_id.rsplit("-", 1)[0]
    return ""
