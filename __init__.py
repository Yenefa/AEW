"""AEW — Project Situational Awareness (v0) + Terminal Decision Layer (v1).

v0 answers ONE question: "what is this project's actual current situation?"
v1 adds a long-running Terminal Agent that turns that situation into dispatchable
task cards (difficulty-rated, model-routed) — without becoming an agent platform.
"""

from .deps import parallel_ready
from .model import (
    Branch,
    CIStatus,
    Decision,
    Event,
    Issue,
    ProjectIdentity,
    ProjectSnapshot,
    PullRequest,
    ReleaseState,
    ResultCard,
    Task,
    TaskCard,
)

__all__ = [
    "ProjectIdentity",
    "Task",
    "Event",
    "Decision",
    "ProjectSnapshot",
    "parallel_ready",
    # v1
    "PullRequest",
    "Issue",
    "CIStatus",
    "Branch",
    "ReleaseState",
    "TaskCard",
    "ResultCard",
]
