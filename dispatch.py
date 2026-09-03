"""Agent Dispatch — hand a Task Card to a worker Agent.

AEW is the *decision* layer; it does not execute the work itself. Dispatch turns
a Task Card into a self-contained prompt + the shell command that feeds it to a
worker (OpenCode / Claude Code / Codex / a generic API agent). `dry_run` defaults
to True: AEW prints the command instead of launching a long-running subprocess,
so the human stays in control of when real execution happens.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from .model import TaskCard

# target -> (binary, flag used to feed a prompt from the CLI)
_AGENTS: Dict[str, Dict[str, str]] = {
    "opencode": {"cmd": "opencode", "flag": "run"},
    "claude": {"cmd": "claude", "flag": "-p"},
    "codex": {"cmd": "codex", "flag": "exec"},
    "api": {"cmd": "", "flag": ""},   # no shell; output the card for an API agent
}


def available_agents() -> List[str]:
    """Return the worker agents installed on this machine."""
    found: List[str] = []
    for name, spec in _AGENTS.items():
        if name == "api":
            continue
        if shutil.which(spec["cmd"]):
            found.append(name)
    return found


def card_prompt(card: TaskCard, cwd: Path) -> str:
    """A self-contained prompt a worker can execute without re-deriving context."""
    return (
        "You are executing a single task on behalf of AEW (the project manager).\n"
        f"Working directory: {cwd}\n\n"
        "=== TASK CARD ===\n"
        f"{card.render()}\n"
        "=== END TASK CARD ===\n\n"
        "Do exactly this task. When finished, reply with a RESULT CARD:\n"
        f"task_id: {card.task_id}\n"
        "status: done | failed | partial\n"
        "summary: <one or two sentences>\n"
        "artifacts: <list of changed file paths>\n"
    )


def dispatch_command(card: TaskCard, target: str, cwd: Path) -> str:
    """Build the shell command for a target (empty string for unsupported/API)."""
    spec = _AGENTS.get(target.lower())
    if spec is None:
        raise ValueError(f"unknown target agent: {target!r}")
    if spec["cmd"] == "":
        return ""   # API agent: the card is the deliverable
    prompt = card_prompt(card, cwd)
    return f'{spec["cmd"]} {spec["flag"]} {_sh_quote(prompt)}'


def _sh_quote(s: str) -> str:
    """Minimal single-quote escaping so the prompt survives one shell hop."""
    return "'" + s.replace("'", "'\\''") + "'"


def dispatch(card: TaskCard, target: str, cwd: Path, dry_run: bool = True) -> str:
    """Return the command (dry run) or actually run it and return its output.

    Returns the command string for `api`/dry-run, or the subprocess output when
    actually executing. `dry_run=True` never spawns a worker.
    """
    cmd = dispatch_command(card, target, cwd)
    if cmd == "":
        return f"[{target}] — API agent: pass this card directly:\n\n{card.render()}"
    if dry_run:
        return cmd
    try:
        out = subprocess.run(
            cmd, cwd=str(cwd), shell=True, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=600,
        )
        return out.stdout.strip() or out.stderr.strip()
    except Exception as e:
        return f"[{target}] dispatch failed: {e}"
