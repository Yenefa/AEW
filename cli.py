"""AEW v0 CLI — print a project's situational snapshot.

Usage:
    python cli.py <repo-path>
"""

import sys
from pathlib import Path

from .loaders.aedl import load_project


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python cli.py <repo-path>")
        return 2
    repo = Path(argv[0])
    snap = load_project(repo)
    print(snap.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
