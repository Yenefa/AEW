"""Sync — turn the live project snapshot into stable, upsertable team tasks.

The planner (`planner.plan`) derives *local* tasks whose IDs are unstable
(`PROJECT-YYYYMMDD-NNN`); the Hub needs IDs stable across 100 refreshes, so sync
re-uses the planner's *rating* function and the router's *model* function but
builds its own candidates with stable IDs + a `source` tag.

Ownership lives in the store, not here: `refresh()` only *discovers* candidates
and UPSERTs them, and `Store.upsert` refuses to touch CLAIMED/DONE rows.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List

from ..loaders.aedl import load_project
from ..model import ProjectSnapshot
from ..planner import _infer_flags, rate_difficulty
from ..router import route
from .models import BLOCKED, READY, TeamTask


def _slug(name: str) -> str:
    s = "".join(ch if ch.isalnum() else "-" for ch in (name or "")).strip("-")
    return (s or "PROJ").upper()[:20]


def _stable_id(project: str, source: str, key: str) -> str:
    if source == "native":
        return f"{_slug(project)}-{key}"
    if source == "pr":
        return f"GH-PR-{key}"
    if source == "issue":
        return f"GH-ISSUE-{key}"
    if source == "ci":
        return f"GH-CI-{key or 'default'}"
    return f"TASK-{key}"


def derive_candidates(snap: ProjectSnapshot) -> List[TeamTask]:
    """Derive READY/BLOCKED team tasks with stable IDs (no ownership info)."""
    out: List[TeamTask] = []
    project = snap.project.name or ""
    blocked = set(snap.blocked_by_deps)

    # 1. Native repo tasks: only OPEN tasks are candidates (DONE/CLAIMED belong to
    #    the store's coordination state, not the repo's fact layer).
    for t in snap.tasks:
        if t.status.upper() != "OPEN":
            continue
        st = BLOCKED if t.task_id in blocked else READY
        files, hw, sec, cross = _infer_flags(t.description, t.assets)
        diff = rate_difficulty(
            files_count=files, hardware=hw, security=sec,
            cross_module=cross, needs_verification=hw,
        )
        out.append(TeamTask(
            task_id=_stable_id(project, "native", t.task_id),
            title=f"Implement {t.task_id}",
            source="native",
            status=st,
            difficulty=diff,
            recommended_model=route(diff),
        ))

    # 2. Open PRs awaiting review / with requested changes.
    for pr in snap.pull_requests:
        if pr.state != "open" or pr.draft:
            continue
        if pr.review_status in ("", "REVIEW_REQUIRED", "CHANGES_REQUESTED"):
            changed = pr.review_status == "CHANGES_REQUESTED"
            diff = rate_difficulty(files_count=2, needs_verification=changed)
            out.append(TeamTask(
                task_id=_stable_id(project, "pr", str(pr.number)),
                title=f"Review PR #{pr.number}",
                source="pr",
                status=READY,
                difficulty=diff,
                recommended_model=route(diff),
            ))

    # 3. Open issues (triage, not build).
    for issue in snap.issues:
        if issue.state == "open":
            diff = rate_difficulty()
            out.append(TeamTask(
                task_id=_stable_id(project, "issue", str(issue.number)),
                title=f"Triage issue #{issue.number}",
                source="issue",
                status=READY,
                difficulty=diff,
                recommended_model=route(diff),
            ))

    # 4. A failed CI run blocks everything.
    if snap.ci.state in ("failure", "failing", "error", "timed_out"):
        diff = rate_difficulty(needs_verification=True)
        out.append(TeamTask(
            task_id=_stable_id(project, "ci", snap.ci.ref or "default"),
            title="Fix CI failure",
            source="ci",
            status=READY,
            difficulty=diff,
            recommended_model=route(diff),
        ))

    return out


def refresh(store, repo: Path | str, github: bool = True) -> Dict[str, object]:
    """git fetch (best-effort) → snapshot → derive → upsert (never clobber)."""
    repo = Path(repo)
    _git_fetch(repo)
    snap = load_project(repo, github=github)
    candidates = derive_candidates(snap)
    upserted = 0
    for c in candidates:
        if store.upsert(c):
            upserted += 1
    return {
        "project": snap.project.name or "",
        "upserted": upserted,
        "total": len(store.list_tasks()),
    }


def _git_fetch(repo: Path) -> None:
    try:
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "--all", "--quiet"],
            capture_output=True, timeout=20,
        )
    except Exception:
        pass
