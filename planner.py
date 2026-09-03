"""Task Planner + Difficulty Rating — turn a snapshot into dispatchable task cards.

The planner is deterministic, in the same spirit as `deps.parallel_ready`: it
derives tasks from *explicit signals* already present in the snapshot (a failed
CI run, a PR awaiting review, an OPEN task, an open issue). It does not invent
work. Its job is triage + sizing, not creativity.

A task card leaves `recommended_model` empty — the Model Router fills that in
after difficulty is computed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from .ids import stable_id
from .model import ProjectSnapshot, TaskCard


# --------------------------------------------------------------------------- #
# Difficulty rating (0-10)                                                     #

# Factor weights (from the proposal). Each is an *additive* signal.
_FACTORS = {
    "files": 1,            # 修改文件 > 5
    "cross_module": 2,     # 跨模块
    "architecture": 3,     # 架构变化
    "hardware": 2,         # 硬件影响
    "needs_verification": 1,  # 需要验证
    "security": 2,         # 涉及安全/合规
}


def rate_difficulty(
    files_count: int = 0,
    cross_module: bool = False,
    architecture: bool = False,
    hardware: bool = False,
    needs_verification: bool = False,
    security: bool = False,
) -> int:
    """Return a 0-10 difficulty score from explicit signals."""
    score = 0
    if files_count > 5:
        score += _FACTORS["files"]
    if cross_module:
        score += _FACTORS["cross_module"]
    if architecture:
        score += _FACTORS["architecture"]
    if hardware:
        score += _FACTORS["hardware"]
    if needs_verification:
        score += _FACTORS["needs_verification"]
    if security:
        score += _FACTORS["security"]
    return min(10, score)


def difficulty_band(score: int) -> str:
    """Map a 0-10 score to a model tier.

        0-3  simple          -> Flash model
        4-7  standard        -> mid-range model
        8-10 architectural   -> flagship model
    """
    if score <= 3:
        return "simple"
    if score <= 7:
        return "standard"
    return "architectural"


_HW_HINTS = ("hardware", "硬件", "board", "板", "schematic", "pcb")
_SEC_HINTS = ("security", "compliance", "合规", "安全", "审计")


def _infer_flags(description: str, assets: List[str]):
    """Infer difficulty signals from a task's declared scope.

    Returns (files_count, hardware, security, cross_module). Light-touch keyword
    heuristics only — the goal is a sane default, not perfect classification.
    """
    text = (description + " " + " ".join(assets)).lower()
    files = len(assets)
    hardware = any(h in text for h in _HW_HINTS)
    security = any(s in text for s in _SEC_HINTS)
    tops = {a.split("/")[0] for a in assets if a and a not in {".", "/"}}
    cross_module = len(tops) > 1
    return files, hardware, security, cross_module


# --------------------------------------------------------------------------- #
# Planned task                                                                 #

@dataclass
class PlannedTask:
    card: TaskCard
    priority: str = "Medium"       # High / Medium / Low
    reason: str = ""

    def render(self) -> str:
        return (
            f"[{self.priority:<6}] {self.card.title}  "
            f"(difficulty {self.card.difficulty}/10 · "
            f"{difficulty_band(self.card.difficulty)})\n"
            f"          {self.reason}"
        )


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-")[:24] or "item"


def _make_card(
    task_id: str, project: str, title: str, objective: str,
    stage: str, files: List[str], constraints: List[str],
    difficulty: int, acceptance: List[str],
    dependencies: Optional[List[str]] = None,
    forbidden_paths: Optional[List[str]] = None,
) -> TaskCard:
    return TaskCard(
        task_id=task_id,
        title=title,
        objective=objective,
        project=project,
        current_stage=stage,
        constraints=constraints,
        files=files,
        difficulty=difficulty,
        acceptance=acceptance,
        dependencies=dependencies or [],
        forbidden_paths=forbidden_paths or [],
    )


# --------------------------------------------------------------------------- #
# Planner                                                                      #

def plan(snapshot: ProjectSnapshot, focus: Optional[dict] = None) -> List[PlannedTask]:
    """Derive dispatchable tasks from snapshot signals, highest priority first."""
    out: List[PlannedTask] = []
    project = snapshot.project.name or ""

    # 1. Failed CI blocks everything.
    if snapshot.ci.state in ("failure", "failing", "error", "timed_out"):
        out.append(PlannedTask(
            card=_make_card(
                stable_id(project, "ci", snapshot.ci.ref or "default"),
                project, "Fix CI failure",
                f"Restore a green build on {snapshot.ci.ref or 'main'}.",
                "CI", ["."], ["Do not merge while red"],
                rate_difficulty(needs_verification=True),
                ["CI passes", "explain root cause"],
            ),
            priority="High",
            reason=f"Blocking merge: {snapshot.ci.conclusion or snapshot.ci.state}",
        ))

    # 2. PRs awaiting review / with requested changes.
    for pr in snapshot.pull_requests:
        if pr.state != "open" or pr.draft:
            continue
        if pr.review_status in ("", "REVIEW_REQUIRED", "CHANGES_REQUESTED"):
            changed = pr.review_status == "CHANGES_REQUESTED"
            out.append(PlannedTask(
                card=_make_card(
                    stable_id(project, "pr", str(pr.number)),
                    project, f"Review PR #{pr.number}",
                    f"Review {pr.title!r} and either approve or request changes.",
                    "Review", [f"PR #{pr.number}"],
                    ["Preserve existing ADR decisions"],
                    rate_difficulty(files_count=2, needs_verification=changed),
                    ["Review submitted", "decision recorded"],
                ),
                priority="High" if pr.review_status == "CHANGES_REQUESTED" else "Medium",
                reason=f"PR #{pr.number} — {pr.review_status or 'awaiting review'}",
            ))

    # 3. Unfinished threads from the previous session (persistent memory).
    focus = focus or {}
    for item in focus.get("unfinished_tasks", []):
        out.append(PlannedTask(
            card=_make_card(
                stable_id(project, "native", "resume-" + _slug(item)),
                project, f"Resume: {item}",
                f"Pick up unfinished thread '{item}' from last session.",
                "Resume", [], [],
                rate_difficulty(),
                ["thread resolved or re-triaged"],
            ),
            priority="High",
            reason=f"unfinished from {focus.get('last_session', 'previous session')}",
        ))

    # 4. Tasks the DAG already declared ready to pick up.
    for task in snapshot.tasks:
        if task.task_id in snapshot.parallel_ready:
            files, hardware, security, cross = _infer_flags(
                task.description, task.assets)
            difficulty = (
                task.difficulty if task.difficulty is not None
                else rate_difficulty(files_count=files, hardware=hardware,
                                     security=security, cross_module=cross,
                                     needs_verification=hardware)
            )
            out.append(PlannedTask(
                card=_make_card(
                    stable_id(project, "native", task.task_id),
                    project, f"Implement {task.task_id}",
                    task.description or f"Advance {task.task_id} to DONE.",
                    "Build", task.assets or ["."], [],
                    difficulty,
                    ["tests pass", "task marked DONE"],
                    dependencies=task.dependencies,
                ),
                priority="Medium",
                reason=f"{task.task_id} is parallel-ready",
            ))

    # 5. Open issues (lowest: triage, not build).
    for issue in snapshot.issues:
        if issue.state == "open":
            out.append(PlannedTask(
                card=_make_card(
                    stable_id(project, "issue", str(issue.number)),
                    project, f"Triage issue #{issue.number}",
                    f"Read issue #{issue.number}: {issue.title}",
                    "Triage", [], [],
                    rate_difficulty(),
                    ["issue labeled/prioritized", "owner assigned or closed"],
                ),
                priority="Low",
                reason=f"open issue #{issue.number}",
            ))

    return out
