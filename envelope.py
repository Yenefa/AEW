"""Task Envelope builder — the bridge from AEW's TaskCard to AECP's Task Envelope.

AEW is the *decision* layer (TaskCard); AEDL's AECP is the *execution* control
plane (Task Envelope at `tasks/GH-N.yaml`). This module completes a TaskCard
into a legal envelope so a task AEW planned can actually be consumed by AECP's
`admit` / `dev_gate`.

Machine fields (parsed strictly by AEDL `tools/envelope.py`):
    task / base(branch + sha) / dependencies / allowed_paths / forbidden_paths / exceptions
Everything else (goal / scope / acceptance / change_budget / escalation) is
opaque free text preserved for humans.

Field mapping (TaskCard -> Envelope):
    task_id            -> task
    files              -> allowed_paths   (owned paths = writable whitelist)
    forbidden_paths    -> forbidden_paths
    dependencies       -> dependencies    (required_state defaults to merged)
    objective / title  -> goal
    acceptance         -> acceptance
    (repo git HEAD)    -> base.branch + base.sha   (approval-time baseline)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from .model import TaskCard


def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def current_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def current_branch(repo: Path) -> str:
    return _git(repo, "branch", "--show-current") or "master"


def _module_tops(paths: List[str]) -> List[str]:
    tops = {p.split("/")[0] for p in paths if p and p not in {".", "/"}}
    return sorted(tops)


def build_envelope(
    card: TaskCard,
    repo: Path,
    base_sha: Optional[str] = None,
    branch: Optional[str] = None,
    forbidden_paths: Optional[List[str]] = None,
    goal: Optional[str] = None,
    scope: Optional[str] = None,
    escalation_owner: str = "",
) -> str:
    """Render a legal AECP Task Envelope YAML for a TaskCard."""
    base_sha = base_sha or current_head(repo)
    branch = branch or current_branch(repo)
    forbidden = forbidden_paths if forbidden_paths is not None else card.forbidden_paths
    allowed = [p for p in (card.files or []) if p and p != "."]
    tops = _module_tops(allowed)

    L: List[str] = []
    A = L.append
    A(f"# Task Envelope — auto-generated from AEW TaskCard {card.task_id}")
    A("# Human review + admission required before execution.")
    A("")
    A(f"task: {card.task_id}")
    A("")
    A("base:")
    A(f"  branch: {branch}")
    A(f"  sha: {base_sha or '<approval-time-SHA>'}  # HEAD drift = BLOCKED")
    A("")
    A("goal: |")
    A(f"  {goal or card.objective or card.title}")
    A("")
    A("scope: |")
    A(f"  {scope or 'Writable paths are whitelisted in allowed_paths; everything else is FOREIGN (read-only).'}")
    A("")
    A("dependencies:")
    if card.dependencies:
        for d in card.dependencies:
            A(f"  - ref: {d}")
            A("    required_state: merged")
    else:
        L[-1] = "dependencies: []"
    A("")
    A("allowed_paths:")
    if allowed:
        for p in allowed:
            A(f"  - {p}")
    else:
        L[-1] = "allowed_paths: []"
    A("")
    A("forbidden_paths:")
    if forbidden:
        for p in forbidden:
            A(f"  - {p}")
    else:
        L[-1] = "forbidden_paths: []"
    A("")
    A("acceptance: |")
    for a in (card.acceptance or ["task marked DONE"]):
        A(f"  - {a}")
    A("")
    A("change_budget:")
    A(f"  expected_files: {len(allowed)}")
    A(f"  expected_modules: [{', '.join(tops)}]")
    A(f"  cross_module: {'true' if len(tops) > 1 else 'false'}")
    A("  contract_change: false")
    A("  evidence_semantics_change: false")
    A("")
    A("exceptions:")
    A("  # Agent cannot self-authorize. Add allow_dirty / allow_drift / skip_deps")
    A("  # only with a human-granted authority (permitted+authority or granted_by+decision_ref).")
    if escalation_owner:
        A("")
        A("escalation:")
        A(f"  owner: {escalation_owner}")
    return "\n".join(L)


def envelope_path(repo: Path, card: TaskCard, tasks_dir: str = "tasks") -> Path:
    """Where this card's envelope should live: <repo>/tasks/<task_id>.yaml."""
    return repo / tasks_dir / f"{card.task_id}.yaml"


def write_envelope(
    card: TaskCard,
    repo: Path,
    tasks_dir: str = "tasks",
    **kwargs,
) -> Path:
    """Write the envelope to <repo>/tasks/<task_id>.yaml and return its path."""
    path = envelope_path(repo, card, tasks_dir=tasks_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_envelope(card, repo, **kwargs) + "\n", encoding="utf-8")
    return path
