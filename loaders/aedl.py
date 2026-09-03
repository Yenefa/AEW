"""Repo-native loader — read the project's existing truth sources.

Repo-native first: AEW does NOT ask the project to re-file its state into AEW.
It stands ON TOP of the existing project and resolves scattered sources into a
unified ProjectSnapshot.

Truth sources are discovered by convention, not hard-coded to AEDL's exact
paths (the original v0 coupled discovery to `docs/WAVE4_TASKS_20260901.md` and
`docs/compliance/DECISIONS.md`, which read as empty on any non-AEDL project):

    README.md / CLAUDE.md / AGENTS.md           -> project identity
    docs/** + root: *TASK* / TODO / PLAN / ...  -> tasks (status + paths + deps)
    docs/** + root: *DECISION* / ADR / CLAUDE   -> decisions (ADR + design)
    git log                                     -> recent activity
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List

from ..deps import parallel_ready
from ..model import Decision, Event, ProjectIdentity, ProjectSnapshot, Task


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _section(text: str, start: int, boundary: str = r"\n## ") -> str:
    nxt = re.search(boundary, text[start + 1:])
    end = start + 1 + nxt.start() if nxt else len(text)
    return text[start:end]


def _identity(repo: Path) -> ProjectIdentity:
    text = ""
    for fname in ("README.md", "CLAUDE.md", "AGENTS.md"):
        text = _read_text(repo / fname)
        if text.strip():
            break
    name, tagline, north_star = "", "", ""
    for line in text.splitlines():
        if line.startswith("# ") and not name:
            name = line[2:].strip()
        if "**" in line and not tagline and line.strip().startswith("**"):
            tagline = line.strip().strip("*").strip()
        if "北极星" in line and not north_star:
            m = re.search(r"北极星\**：?\**(.+)", line)
            if m:
                north_star = re.sub(r"\*+", "", m.group(1)).strip()
    return ProjectIdentity(name=name, tagline=tagline, north_star=north_star)


# --------------------------------------------------------------------------- #
# tasks — discover by structure, not by hard-coded IDs (P3)                   #
# --------------------------------------------------------------------------- #

_TASK_NAME_RE = re.compile(r"(TASK-[A-Za-z0-9_-]+|[A-Z][A-Za-z0-9-]*(?:\s+V?\d+)?)")


def _task_status(cell: str) -> str:
    return re.split(r"[；;]", cell.replace("`", ""))[0].strip().upper()


_TASK_FILE_PAT = re.compile(
    r"(task|tasks|todo|plan|backlog|roadmap|任务|待办|计划|清单)", re.IGNORECASE
)


def _task_files(repo: Path) -> List[Path]:
    """Discover task-bearing markdown by name convention (not AEDL's path)."""
    found: dict[str, Path] = {}
    docs = repo / "docs"
    roots: List[Path] = [docs] if docs.is_dir() else []
    roots.append(repo)
    for base in roots:
        # docs subtree recursive; repo root top-level only (avoid data/, venv/).
        it = base.rglob("*.md") if base == docs else base.glob("*.md")
        for p in it:
            if p.is_file() and _TASK_FILE_PAT.search(p.name):
                found[p.as_posix()] = p
    return sorted(found.values())


def _parse_tasks(text: str, tasks: dict[str, Task]) -> None:
    # 1. tracking table: rows with an Issue # carry the authoritative status
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or "Issue" not in cells[1]:
            continue
        # Skip the header row (`| Task | Issue | ...`) and separator (`---`).
        if cells[0].lower() in {"task", "tasks", "id", "任务"}:
            continue
        m = _TASK_NAME_RE.match(cells[0])
        if not m:
            continue
        tid = re.sub(r"^TASK-", "", m.group(1)).replace(" ", "-")
        tasks[tid] = Task(
            task_id=tid,
            status=_task_status(cells[3]),
            description=cells[2] if len(cells) > 2 else "",
            assets=_assets_for_task(text, tid),
            dependencies=_deps_for_task(text, tid),
        )

    # 2. `## TASK-*` section headers discover any task the table missed
    for m in re.finditer(r"^## (TASK-[A-Za-z0-9_-]+)", text, re.MULTILINE):
        tid = re.sub(r"^TASK-", "", m.group(1))
        if tid not in tasks:
            tasks[tid] = Task(
                task_id=tid,
                status="OPEN",
                assets=_assets_for_task(text, tid),
                dependencies=_deps_for_task(text, tid),
            )


def _tasks(repo: Path) -> List[Task]:
    tasks: dict[str, Task] = {}
    for f in _task_files(repo):
        _parse_tasks(_read_text(f), tasks)
    return list(tasks.values())


def _assets_for_task(text: str, task_id: str) -> List[str]:
    m = re.search(rf"## TASK-{re.escape(task_id)}\b", text)
    if not m:
        return []
    section = _section(text, m.start())
    territory = re.search(r"领地[（(]?可写[)）]?：?([^\n]+)", section)
    if not territory:
        return []
    return re.findall(r"`([^`]+)`", territory.group(1))


def _deps_for_task(text: str, task_id: str) -> List[str]:
    """Parse declared dependencies from a task section (empty if none declared).

    AEDL's W4 tasks declare no machine-readable task-to-task dependencies, so
    this returns [] today — but the mechanism reads whatever is declared.
    """
    m = re.search(rf"## TASK-{re.escape(task_id)}\b", text)
    if not m:
        return []
    section = _section(text, m.start())
    deps: List[str] = []
    for m in re.finditer(r"(?:依赖|depends\s+on|前置条件)[：:\s]*([A-Za-z0-9_-]+)", section):
        d = m.group(1)
        if d and d.upper() != task_id.upper():
            deps.append(d)
    return deps


# --------------------------------------------------------------------------- #
# events / decisions                                                          #
# --------------------------------------------------------------------------- #

def _events(repo: Path, limit: int = 8) -> List[Event]:
    try:
        out = subprocess.run(
            ["git", "log", "--pretty=format:%ad %s", "--date=format:%m-%d %H:%M", f"-n{limit}"],
            cwd=str(repo), capture_output=True, text=True, encoding="utf-8", timeout=10,
        ).stdout
    except Exception:
        return []
    return [Event(timestamp=ln[:11].strip(), description=ln[12:].strip()) for ln in out.splitlines() if ln.strip()]


def _normalize_decision_status(raw: str) -> str:
    r = raw.strip().lower()
    if r.startswith("superseded") or r.startswith("deprecated"):
        return "superseded"
    if r.startswith("accepted"):
        return "current"
    if r.startswith("proposed"):
        return "proposed"
    if r.startswith("rejected"):
        return "rejected"
    return "unknown"


_DECISION_FILE_PAT = re.compile(r"(decision|adr|决策|决定)", re.IGNORECASE)


def _decision_files(repo: Path) -> List[Path]:
    """Discover decision/ADR markdown by convention, plus CLAUDE/AGENTS context."""
    found: dict[str, Path] = {}
    docs = repo / "docs"
    roots: List[Path] = [docs] if docs.is_dir() else []
    roots.append(repo)
    for base in roots:
        it = base.rglob("*.md") if base == docs else base.glob("*.md")
        for p in it:
            if p.is_file() and _DECISION_FILE_PAT.search(p.name):
                found[p.as_posix()] = p
    # CLAUDE.md / AGENTS.md carry a "设计决策" section for modern AI projects.
    for fname in ("CLAUDE.md", "AGENTS.md"):
        p = repo / fname
        if p.is_file():
            found[p.as_posix()] = p
    return sorted(found.values())


def _parse_adr_decisions(text: str, decisions: List[Decision]) -> None:
    """Parse `## ADR-* — title` headings AND their `状态：...` line."""
    for m in re.finditer(r"^## (ADR-\d+)\s*[—–-]\s*(.+)", text, re.MULTILINE):
        section = _section(text, m.start())
        sm = re.search(r"状态[：:]\s*\**(.+?)\**\s*[（(]", section)
        if not sm:
            sm = re.search(r"状态[：:]\s*\**(.+?)\**\s*$", section, re.MULTILINE)
        raw = sm.group(1).strip() if sm else ""
        decisions.append(
            Decision(
                decision_id=m.group(1),
                text=m.group(2).strip(),
                status=_normalize_decision_status(raw),
            )
        )


_DESIGN_SECTION_RE = re.compile(
    r"^#{1,4}\s*(设计决策|设计决定|设计考量|Design Decisions?)\s*$", re.MULTILINE
)


def _parse_design_decisions(text: str, decisions: List[Decision]) -> None:
    """Parse a `## 设计决策` bullet list (CLAUDE.md / AGENTS.md) as decisions."""
    m = _DESIGN_SECTION_RE.search(text)
    if not m:
        return
    section = _section(text, m.start())
    idx = len(decisions) + 1
    for line in section.splitlines():
        s = line.strip()
        if s.startswith("- "):
            item = s[2:].strip()
        elif re.match(r"^\d+\.\s", s):
            item = re.sub(r"^\d+\.\s*", "", s).strip()
        else:
            continue
        if item:
            decisions.append(Decision(decision_id=f"DD-{idx:03d}", text=item, status="current"))
            idx += 1


def _decisions(repo: Path) -> List[Decision]:
    decisions: List[Decision] = []
    for f in _decision_files(repo):
        text = _read_text(f)
        _parse_adr_decisions(text, decisions)
        _parse_design_decisions(text, decisions)
    return decisions


def load_project(repo: str | Path, github: bool = False) -> ProjectSnapshot:
    """Build the snapshot.

    `github=False` (default) preserves v0's exact six-field contract. Pass
    `github=True` to also project PRs / issues / CI / branches / releases from
    the GitHub remote — empty when offline or not a GitHub repo.
    """
    repo = Path(repo)
    tasks = _tasks(repo)
    ready, blocked = parallel_ready(tasks)
    snap = ProjectSnapshot(
        project=_identity(repo),
        tasks=tasks,
        events=_events(repo),
        decisions=_decisions(repo),
        parallel_ready=ready,
        blocked_by_deps=blocked,
    )
    if github:
        from ..github import load_github_state
        gs = load_github_state(repo)
        snap.pull_requests = gs["pull_requests"]  # type: ignore[assignment]
        snap.issues = gs["issues"]  # type: ignore[assignment]
        snap.ci = gs["ci"]  # type: ignore[assignment]
        snap.branches = gs["branches"]  # type: ignore[assignment]
        snap.release = gs["release"]  # type: ignore[assignment]
    return snap
