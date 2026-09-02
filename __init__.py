"""AEW v0 — Project Situational Awareness.

v0 answers ONE question: "what is this project's actual current situation?"
It reads the project's existing truth sources and projects a unified
ProjectSnapshot. v0 does NOT execute, schedule, or enforce — that is AECP's
job, later.
"""

from .deps import parallel_ready
from .model import (
    Decision,
    Event,
    ProjectIdentity,
    ProjectSnapshot,
    Task,
)

__all__ = [
    "ProjectIdentity",
    "Task",
    "Event",
    "Decision",
    "ProjectSnapshot",
    "parallel_ready",
]
