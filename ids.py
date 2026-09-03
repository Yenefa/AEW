"""Stable task IDs — the single source of truth for cross-refresh identities.

The planner's old `PROJECT-YYYYMMDD-NNN` changed on every run, which breaks any
downstream that needs to refer to "the same task" across refreshes (the Hub, PRs,
AECP envelopes). Stable identities instead derive from durable source facts:

    native task   -> {PROJECT}-{task_id}   e.g. AEDL-W4A
    PR            -> GH-PR-{number}        e.g. GH-PR-42
    issue         -> GH-ISSUE-{number}     e.g. GH-ISSUE-37
    CI            -> GH-CI-{ref}           e.g. GH-CI-main   (ref, NOT run_id: run_id changes every run)
"""

from __future__ import annotations


def project_slug(name: str) -> str:
    s = "".join(ch if ch.isalnum() else "-" for ch in (name or "")).strip("-")
    return (s or "PROJ").upper()[:20]


def stable_id(project: str, source: str, key: str) -> str:
    """Build a stable team/task ID from a durable source fact.

    source ∈ {native, pr, issue, ci}; key is the durable identifier for that
    source (task_id / PR number / issue number / CI ref).
    """
    if source == "native":
        return f"{project_slug(project)}-{key}"
    if source == "pr":
        return f"GH-PR-{key}"
    if source == "issue":
        return f"GH-ISSUE-{key}"
    if source == "ci":
        return f"GH-CI-{key or 'default'}"
    return f"TASK-{key}"
