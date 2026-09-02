"""AEW v0 — Project Situational Awareness data model.

v0 answers exactly ONE question:

    "I just entered this project — what is its actual current situation?"

It produces a ProjectSnapshot with six fields:
    1. project identity
    2. current tasks
    3. recent activity
    4. active decisions
    5. relevant assets
    6. parallel-ready tasks

v0 does NOT execute tasks, launch agents, schedule models, or enforce control.
It only reads existing project truth sources and projects a unified view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ProjectIdentity:
    name: str = ""
    tagline: str = ""
    north_star: str = ""


@dataclass
class Task:
    task_id: str
    status: str = "OPEN"           # OPEN / BLOCKED / DONE / CLAIMED ...
    description: str = ""
    dependencies: List[str] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)


@dataclass
class Event:
    timestamp: str
    description: str


@dataclass
class Decision:
    decision_id: str
    text: str
    ref: str = ""
    status: str = "unknown"        # current / superseded / proposed / rejected / unknown


@dataclass
class ProjectSnapshot:
    project: ProjectIdentity = field(default_factory=ProjectIdentity)
    tasks: List[Task] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)
    parallel_ready: List[str] = field(default_factory=list)
    blocked_by_deps: List[str] = field(default_factory=list)

    def render(self) -> str:
        """Human-readable snapshot (the product)."""
        L: List[str] = []
        A = L.append
        A("AEW PROJECT SNAPSHOT")
        A("─" * 44)
        A("")
        A("Project")
        name = self.project.name or "(unknown)"
        tagline = f" — {self.project.tagline}" if self.project.tagline else ""
        A(f"{name}{tagline}")
        if self.project.north_star:
            A(f"north star: {self.project.north_star}")
        A("")

        A("Current Tasks")
        if self.tasks:
            for t in self.tasks:
                desc = f"  {t.description}" if t.description else ""
                A(f"{t.task_id:<12} {t.status}{desc}")
        else:
            A("  (none)")
        A("")

        A("Recent Activity")
        if self.events:
            for e in self.events:
                A(f"{e.timestamp}  {e.description}")
        else:
            A("  (none)")
        A("")

        A("Active Decisions")
        active = [d for d in self.decisions if d.status == "current"]
        if active:
            for d in active:
                A(f"[{d.decision_id}] {d.text}")
                if d.ref:
                    A(f"        ref: {d.ref}")
        else:
            A("  (none)")
        A("")

        A("Declared Assets (owned paths)")
        if self.tasks:
            for t in self.tasks:
                if t.assets:
                    A(f"{t.task_id}")
                    for a in t.assets:
                        A(f"  {a}")
        else:
            A("  (none)")
        A("")

        A("Parallel-ready (declared dependencies)")
        if self.parallel_ready:
            for t in self.parallel_ready:
                A(t)
        else:
            A("  (none)")
        A("")

        A("Blocked by dependencies")
        if self.blocked_by_deps:
            for t in self.blocked_by_deps:
                A(t)
        else:
            A("  (none)")

        return "\n".join(L)
