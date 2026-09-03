"""GitHub loader — pull PRs / issues / CI / branches / releases into the snapshot.

Repo-native first still holds: AEW reads what the project already exposes. The
difference in v1 is that some truth sources live on GitHub rather than in the
working tree, so the Terminal Agent needs a thin reader for them.

Strategy: prefer the `gh` CLI (auth handled by the user's existing login). If
`gh` is absent, unauthenticated, or the repo has no GitHub remote, every loader
degrades to an empty result — the snapshot simply omits those sections. AEW must
never *fail* just because GitHub is unreachable.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .model import Branch, CIStatus, Issue, PullRequest, ReleaseState


def _run(cmd: List[str], cwd: Path, timeout: int = 15) -> str:
    """Run a command and return stdout; return "" on any failure."""
    try:
        out = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _gh(cwd: Path, *args: str, timeout: int = 20) -> str:
    """Run `gh <args>`; return "" if gh is unavailable or errors."""
    return _run(["gh", *args], cwd, timeout=timeout)


def _json(text: str) -> list:
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def github_remote(cwd: Path) -> Optional[str]:
    """Return 'owner/repo' if the repo has a GitHub remote, else None."""
    url = _run(["git", "remote", "get-url", "origin"], cwd, timeout=10)
    if not url:
        return None
    # Accept ssh (git@github.com:o/r.git) and https (github.com/o/r.git).
    for scheme in ("github.com:", "github.com/"):
        if scheme in url:
            rest = url.split(scheme, 1)[1]
            rest = rest.rstrip("/")
            if rest.endswith(".git"):
                rest = rest[:-4]
            return rest
    return None


def _has_gh(cwd: Path) -> bool:
    return bool(_gh(cwd, "--version"))


# --- PR --------------------------------------------------------------------- #

def load_pull_requests(cwd: Path) -> List[PullRequest]:
    if not (_has_gh(cwd) and github_remote(cwd)):
        return []
    raw = _gh(
        cwd, "pr", "list",
        "--json", "number,title,state,isDraft,reviewDecision,headRefName,baseRefName,author,url,updatedAt",
        "--limit", "20",
    )
    prs: List[PullRequest] = []
    for item in _json(raw):
        author = item.get("author") or {}
        prs.append(PullRequest(
            number=item.get("number", 0),
            title=item.get("title", ""),
            state=item.get("state", "open"),
            draft=bool(item.get("isDraft", False)),
            review_status=item.get("reviewDecision") or "",
            head=item.get("headRefName", ""),
            base=item.get("baseRefName", ""),
            author=author.get("login", ""),
            url=item.get("url", ""),
            updated_at=item.get("updatedAt", ""),
        ))
    return prs


# --- Issues ----------------------------------------------------------------- #

def load_issues(cwd: Path) -> List[Issue]:
    if not (_has_gh(cwd) and github_remote(cwd)):
        return []
    raw = _gh(
        cwd, "issue", "list",
        "--json", "number,title,state,labels,assignees,url",
        "--limit", "20",
    )
    issues: List[Issue] = []
    for item in _json(raw):
        labels = [lb.get("name", "") for lb in (item.get("labels") or []) if lb.get("name")]
        assignees = (item.get("assignees") or [])
        assignee = assignees[0].get("login", "") if assignees else ""
        issues.append(Issue(
            number=item.get("number", 0),
            title=item.get("title", ""),
            state=item.get("state", "open"),
            labels=labels,
            assignee=assignee,
            url=item.get("url", ""),
        ))
    return issues


# --- CI --------------------------------------------------------------------- #

def load_ci(cwd: Path) -> CIStatus:
    if not (_has_gh(cwd) and github_remote(cwd)):
        return CIStatus()
    raw = _gh(
        cwd, "run", "list",
        "--json", "status,conclusion,headBranch,databaseId,url",
        "--limit", "1",
    )
    items = _json(raw)
    if not items:
        return CIStatus()
    item = items[0]
    conclusion = item.get("conclusion") or ""
    state = item.get("status") or "unknown"
    if conclusion and state == "completed":
        state = conclusion  # success / failure / cancelled ...
    return CIStatus(
        ref=item.get("headBranch", ""),
        state=state,
        conclusion=conclusion,
        url=item.get("url", ""),
    )


# --- Branches ---------------------------------------------------------------- #

def load_branches(cwd: Path) -> List[Branch]:
    """Local branches with ahead/behind vs their upstream, when available."""
    out = _run(["git", "branch", "-vv"], cwd, timeout=10)
    branches: List[Branch] = []
    for line in out.splitlines():
        name = line.lstrip("* ").split()[0]
        ahead = behind = 0
        if "ahead" in line:
            part = line.split("ahead", 1)[1]
            digits = "".join(ch for ch in part.split()[0] if ch.isdigit())
            ahead = int(digits) if digits else 0
        if "behind" in line:
            part = line.split("behind", 1)[1]
            digits = "".join(ch for ch in part.split()[0] if ch.isdigit())
            behind = int(digits) if digits else 0
        branches.append(Branch(name=name, ahead=ahead, behind=behind))
    return branches


# --- Release ----------------------------------------------------------------- #

def load_release(cwd: Path) -> ReleaseState:
    """Latest tag + whether a draft release is pending (gh, with git fallback)."""
    if _has_gh(cwd) and github_remote(cwd):
        raw = _gh(cwd, "release", "list", "--json", "tagName,isDraft,url", "--limit", "1")
        items = _json(raw)
        if items:
            item = items[0]
            return ReleaseState(
                latest_tag=item.get("tagName", ""),
                draft=bool(item.get("isDraft", False)),
                url=item.get("url", ""),
            )
    # Fallback: newest git tag only (no draft info).
    tag = _run(["git", "describe", "--tags", "--abbrev=0"], cwd, timeout=10)
    return ReleaseState(latest_tag=tag) if tag else ReleaseState()


# --- Aggregated -------------------------------------------------------------- #

def load_github_state(cwd: Path) -> Dict[str, object]:
    """Collect every GitHub-derived signal at once."""
    return {
        "pull_requests": load_pull_requests(cwd),
        "issues": load_issues(cwd),
        "ci": load_ci(cwd),
        "branches": load_branches(cwd),
        "release": load_release(cwd),
    }
