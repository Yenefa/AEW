"""AEW CLI — snapshot (v0) + Terminal Agent + plan/dispatch (v1).

Usage:
    python -m aew.cli <repo-path>            # v0 snapshot (unchanged)
    python -m aew.cli agent <repo-path>      # start the Terminal Agent REPL
    python -m aew.cli plan <repo-path>       # print the task plan
    python -m aew.cli dispatch <repo> <n>    # print a dispatch command (dry-run)

    Append --github to also project PRs / issues / CI from the remote.
"""

import sys
from pathlib import Path

from .loaders.aedl import load_project


_USAGE = (
    "usage:\n"
    "  python -m aew.cli <repo-path>\n"
    "  python -m aew.cli agent <repo-path> [--github]\n"
    "  python -m aew.cli plan <repo-path> [--github]\n"
    "  python -m aew.cli dispatch <repo-path> <n> [target] [--github]\n"
    "  python -m aew.cli envelope <repo-path> <n>\n"
    "  python -m aew.cli approve <repo-path> <task-id> [--db path] [--user name]  # human-only\n"
    "  python -m aew.cli hub <repo-path> [--host 0.0.0.0] [--port 8765] [--db path]\n"
)


def _github_flag(argv):
    return "--github" in argv


def _run_hub(argv) -> int:
    """Start the Hub server for a repo: python -m aew.cli hub <repo> [options]."""
    import os

    from .hub.api import serve
    from .hub.coordinator import Coordinator
    from .hub.store import Store

    if not argv:
        print("usage: python -m aew.cli hub <repo-path> "
              "[--host 0.0.0.0] [--port 8765] [--db path]")
        return 2
    repo = Path(argv[0])
    host, port, db = "0.0.0.0", 8765, None
    i = 1
    while i < len(argv):
        if argv[i] == "--host" and i + 1 < len(argv):
            host, i = argv[i + 1], i + 2
        elif argv[i] == "--port" and i + 1 < len(argv):
            port, i = int(argv[i + 1]), i + 2
        elif argv[i] == "--db" and i + 1 < len(argv):
            db, i = argv[i + 1], i + 2
        else:
            i += 1
    db_path = Path(db) if db else (repo / ".aew" / "hub.sqlite3")
    token = os.environ.get("AEW_HUB_TOKEN", "")
    store = Store(db_path)
    coord = Coordinator(store, repo, github=True)
    print(f"initial refresh: {coord.refresh()}")
    serve(coord, host=host, port=port, token=token)
    return 0


def _run_approve(argv) -> int:
    """Human-only approval entry: python -m aew.cli approve <repo> <task_id>.

    Runs on the Hub machine against the Hub's SQLite directly (never an HTTP
    endpoint, so a worker subprocess cannot forge approval). Shows what is
    being approved and requires an interactive [y/N] confirmation.
    """
    from .hub.models import TeamTask
    from .hub.store import Store
    import json
    import os

    if not argv:
        print("usage: python -m aew.cli approve <repo-path> <task-id> "
              "[--db path] [--user name] [--run run_id] [--yes]")
        return 2
    repo, task_id = Path(argv[0]), argv[1]
    db, user, run_id, assume_yes = None, os.environ.get("AEW_USER", ""), "", False
    i = 2
    while i < len(argv):
        if argv[i] == "--db" and i + 1 < len(argv):
            db, i = argv[i + 1], i + 2
        elif argv[i] == "--user" and i + 1 < len(argv):
            user, i = argv[i + 1], i + 2
        elif argv[i] == "--run" and i + 1 < len(argv):
            run_id, i = argv[i + 1], i + 2
        elif argv[i] == "--yes":
            assume_yes, i = True, i + 1
        else:
            i += 1
    db_path = Path(db) if db else (repo / ".aew" / "hub.sqlite3")
    store = Store(db_path)
    task = store.get_task(task_id)
    if task is None:
        print(f"task not found: {task_id}")
        return 1
    run_id = run_id or task.active_run_id
    if not run_id:
        print(f"no active run on {task_id}")
        return 1
    run = store.get_run(run_id) or {}
    print(f"TASK:   {task.task_id}  [{task.status}]")
    print(f"RUN:    {run_id}  (generation {task.generation}, worker {run.get('worker') or '?'})")
    print(f"HEAD:   {task.head_sha or '(not reported)'}")
    print(f"RESULT: {run.get('summary') or '(none)'}"
          + (f" · gate {run['gate_status']}" if run.get("gate_status") else ""))
    if assume_yes:
        answer = "y"
    else:
        try:
            answer = input("Approve promotion? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
    if answer != "y":
        print("not approved (no receipt written)")
        return 1
    if not user:
        print("missing approver identity: pass --user or set AEW_USER")
        return 1
    r = store.approve(task_id, run_id, approved_by=user)
    if not r.get("ok"):
        print(f"APPROVAL DENIED — {r.get('reason')}")
        return 1
    print(json.dumps(r["receipt"], ensure_ascii=False, indent=2))
    print("\nNext: run your promotion gate, then `promote` to mark PROMOTED. "
          "Actual git push / merge stays a human action.")
    return 0


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(_USAGE)
        return 2

    sub = argv[0]
    rest = argv[1:]

    if sub in ("agent", "a"):
        from .agent import run_agent
        if not rest:
            print(_USAGE)
            return 2
        return run_agent(rest[0], github=_github_flag(rest))

    if sub in ("approve",):
        return _run_approve(rest)

    if sub in ("envelope", "env"):
        from .envelope import build_envelope
        from .planner import plan
        from .router import load_model_pool, route_card
        if len(rest) < 2:
            print("usage: python -m aew.cli envelope <repo-path> <n>")
            return 2
        repo = Path(rest[0])
        try:
            n = int(rest[1])
        except ValueError:
            print("usage: python -m aew.cli envelope <repo-path> <n>")
            return 2
        snap = load_project(repo, github=_github_flag(rest))
        pool = load_model_pool(repo / "models.yaml")
        planned = plan(snap)
        if not (1 <= n <= len(planned)):
            print(f"no task #{n} (have {len(planned)})")
            return 1
        card = planned[n - 1].card
        route_card(card, pool)
        print(build_envelope(card, repo))
        return 0

    if sub in ("plan", "p"):
        from .planner import plan
        from .router import load_model_pool, route_card
        if not rest:
            print(_USAGE)
            return 2
        repo = Path(rest[0])
        snap = load_project(repo, github=_github_flag(rest))
        pool = load_model_pool(repo / "models.yaml")
        planned = plan(snap)
        for pt in planned:
            route_card(pt.card, pool)
        print("\n\n".join(pt.render() for pt in planned) or "(no planned tasks)")
        return 0

    if sub in ("dispatch", "d"):
        from .dispatch import available_agents, dispatch
        from .planner import plan
        from .router import load_model_pool, route_card
        if len(rest) < 2:
            print(_USAGE)
            return 2
        repo = Path(rest[0])
        try:
            n = int(rest[1])
        except ValueError:
            print(_USAGE)
            return 2
        snap = load_project(repo, github=_github_flag(rest))
        pool = load_model_pool(repo / "models.yaml")
        planned = plan(snap)
        if not (1 <= n <= len(planned)):
            print(f"no task #{n} (have {len(planned)})")
            return 1
        card = planned[n - 1].card
        route_card(card, pool)
        if len(rest) > 2 and not rest[2].startswith("--"):
            target = rest[2]
        else:
            installed = available_agents()
            target = installed[0] if installed else "api"
        print(f"# dispatching '{card.title}' → [{target}] (dry-run)")
        print(dispatch(card, target, repo, dry_run=True))
        return 0

    # default: v0 snapshot
    repo = Path(argv[0])
    snap = load_project(repo, github=_github_flag(rest))
    print(snap.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
