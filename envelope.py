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


def discover_process_paths(
    repo: Path, task_id: str, tasks_dir: str = "tasks"
) -> List[str]:
    """Control-plane artifacts that every task must be allowed to write.

    Discovered by convention, never hard-coded to one project's layout — the
    same rule the repo-native loader follows. Anything a project does not have
    simply contributes nothing, so non-AEDL projects are unaffected.

    Why this exists: the worker is required by the collaboration rules to write
    the ledger and the handoff card, but an envelope holding only the task's
    territory paths makes those writes FOREIGN — so `scope_check` fails on files
    the task was *told* to produce. Leaving the fix to the worker means letting
    an agent edit its own authorization, which is exactly what
    "Agent cannot self-authorize" forbids. The control plane must emit them.

    Recognised conventions:
      - the envelope itself       : <tasks_dir>/<task_id>.yaml
      - the handoff status card    : docs/HANDOFF.md (COLLABORATION §2)
      - the AI usage ledger        : first docs/compliance/*LOG*.md
    """
    found: List[str] = []
    env_rel = f"{tasks_dir}/{task_id}.yaml"
    if (repo / env_rel).parent.is_dir():
        found.append(env_rel)
    for rel in ("docs/HANDOFF.md", "HANDOFF.md"):
        if (repo / rel).is_file():
            found.append(rel)
            break
    compliance = repo / "docs" / "compliance"
    if compliance.is_dir():
        logs = sorted(p for p in compliance.glob("*.md") if "LOG" in p.name.upper())
        if logs:
            found.append(logs[0].relative_to(repo).as_posix())
    return found


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
    territory = [p for p in (card.files or []) if p and p != "."]
    process = [
        p for p in discover_process_paths(repo, card.task_id)
        if p not in territory
    ]
    allowed = territory + process
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
        if territory:
            A("  # territory — owned paths from the task card")
            for p in territory:
                A(f"  - {p}")
        if process:
            A("  # process artifacts — added by the control plane, because the")
            A("  # collaboration rules *require* these writes while the task card")
            A("  # does not own them. Never agent self-authorization.")
            for p in process:
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
    return Path(repo) / tasks_dir / f"{card.task_id}.yaml"


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
