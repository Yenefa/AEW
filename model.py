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


# --------------------------------------------------------------------------- #
# v1 additions — GitHub-aware project state                                    #
#                                                                              #
# v0 projected the six repo-native fields. v1 widens the lens so the Terminal  #
# Agent can also see PRs / issues / CI / branches / releases — the signals a   #
# project manager actually triages. None of this changes v0's contract: these  #
# are read-only projections, not control actions.                              #

@dataclass
class PullRequest:
    number: int
    title: str = ""
    state: str = "open"            # open / closed / merged
    draft: bool = False
    review_status: str = ""        # REVIEW_REQUIRED / APPROVED / CHANGES_REQUESTED
    head: str = ""
    base: str = ""
    author: str = ""
    url: str = ""
    updated_at: str = ""


@dataclass
class Issue:
    number: int
    title: str = ""
    state: str = "open"            # open / closed
    labels: List[str] = field(default_factory=list)
    assignee: str = ""
    url: str = ""


@dataclass
class CIStatus:
    ref: str = ""
    state: str = "unknown"         # success / failure / pending / unknown
    conclusion: str = ""
    url: str = ""


@dataclass
class Branch:
    name: str = ""
    ahead: int = 0
    behind: int = 0


@dataclass
class ReleaseState:
    latest_tag: str = ""
    draft: bool = False
    url: str = ""


# --------------------------------------------------------------------------- #
# v1 additions — task dispatch primitives                                      #
#                                                                              #
# A TaskCard is the *handoff artifact*: any worker Agent (OpenCode, Claude     #
# Code, Codex, an API agent) can pick it up without re-deriving context. A     #
# ResultCard is what comes back.                                               #

@dataclass
class TaskCard:
    task_id: str
    title: str = ""
    objective: str = ""
    project: str = ""
    current_stage: str = ""
    constraints: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    difficulty: int = 0            # 0-10
    recommended_model: str = ""
    acceptance: List[str] = field(default_factory=list)

    def render(self) -> str:
        L: List[str] = []
        A = L.append
        A(f"task_id: {self.task_id}")
        A(f"title: {self.title}")
        A("")
        A(f"objective: {self.objective}")
        A("")
        A("context:")
        A(f"  project: {self.project}")
        A(f"  current_stage: {self.current_stage}")
        A("")
        if self.constraints:
            A("constraints:")
            for c in self.constraints:
                A(f"  - {c}")
            A("")
        if self.files:
            A("files:")
            for f in self.files:
                A(f"  - {f}")
            A("")
        A(f"difficulty: {self.difficulty}")
        A(f"recommended_model: {self.recommended_model}")
        A("")
        if self.acceptance:
            A("acceptance:")
            for a in self.acceptance:
                A(f"  - {a}")
        return "\n".join(L)


@dataclass
class ResultCard:
    task_id: str
    status: str = "done"           # done / failed / partial
    summary: str = ""
    artifacts: List[str] = field(default_factory=list)
    model: str = ""


@dataclass
class ProjectSnapshot:
    project: ProjectIdentity = field(default_factory=ProjectIdentity)
    tasks: List[Task] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)
    parallel_ready: List[str] = field(default_factory=list)
    blocked_by_deps: List[str] = field(default_factory=list)
    # v1 — GitHub-aware state (empty when not a GitHub repo / offline)
    pull_requests: List[PullRequest] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    ci: CIStatus = field(default_factory=CIStatus)
    branches: List[Branch] = field(default_factory=list)
    release: ReleaseState = field(default_factory=ReleaseState)

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

        if self.pull_requests:
            A("Pull Requests")
            for pr in self.pull_requests:
                rs = f" [{pr.review_status}]" if pr.review_status else ""
                draft = " (draft)" if pr.draft else ""
                A(f"  #{pr.number} {pr.title}{rs}{draft}")
            A("")

        if self.issues:
            A("Issues")
            for i in self.issues:
                labels = f" [{', '.join(i.labels)}]" if i.labels else ""
                A(f"  #{i.number} {i.title}{labels}")
            A("")

        if self.ci.ref or self.ci.state != "unknown":
            A("CI Status")
            A(f"  {self.ci.state}{f' — {self.ci.conclusion}' if self.ci.conclusion else ''}")
            A("")

        if self.release.latest_tag:
            draft = " (draft)" if self.release.draft else ""
            A("Release")
            A(f"  {self.release.latest_tag}{draft}")
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
