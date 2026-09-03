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
)


def _github_flag(argv):
    return "--github" in argv


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
