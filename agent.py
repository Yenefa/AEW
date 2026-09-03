"""Terminal Agent — the long-running Project Manager (the decision layer).

It is NOT the executor. On startup it rebuilds the Project Snapshot and recovers
persistent memory, then sits in a loop answering one question over and over:
"what should the team do next?" — sizing each task, picking a model, and handing
off a Task Card to a worker Agent.

The `handle()` method is pure enough to test: `run()` is just a thin input()
loop over it. That keeps the brain testable without a TTY.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .dispatch import available_agents, dispatch
from .loaders.aedl import load_project
from .model import ProjectSnapshot, TaskCard
from .planner import PlannedTask, difficulty_band, plan
from .router import load_model_pool, route_card
from .state import ProjectMemory
from .hub_client import HubClient

TERMINAL_STATES = {"DONE", "CLOSED"}

BANNER = """\
AEW Agent online.
Project: {project}
Status: {status}
Memory: {memory}
{count} task(s) available.

Recommended:
{recommended}
>
"""


class TerminalAgent:
    def __init__(self, repo: Path | str, github: bool = False):
        self.repo = Path(repo)
        self.github = github
        self.memory = ProjectMemory(self.repo)
        self.pool = self._load_pool()
        self.snapshot: ProjectSnapshot = load_project(self.repo, github=github)
        self.plan: List[PlannedTask] = plan(self.snapshot, self.memory.load_focus())
        self._assign_models()
        self.hub: Optional[HubClient] = HubClient.from_env()
        self.user = self.hub.user if self.hub else ""
        self.team_cards: List[TaskCard] = []

    # -- setup -------------------------------------------------------------- #

    def _load_pool(self):
        for name in ("models.yaml", ".aew/models.json", "models.json"):
            p = self.repo / name
            if p.exists():
                return load_model_pool(p)
        return load_model_pool()

    def _assign_models(self) -> None:
        for pt in self.plan:
            route_card(pt.card, self.pool)

    # -- derived state ------------------------------------------------------ #

    def _completion(self) -> int:
        total = len(self.snapshot.tasks)
        if not total:
            return 0
        done = sum(1 for t in self.snapshot.tasks if t.status.upper() in TERMINAL_STATES)
        return int(round(done / total * 100))

    def _open_count(self) -> int:
        return sum(1 for t in self.snapshot.tasks if t.status.upper() not in TERMINAL_STATES)

    def _blocked_count(self) -> int:
        return len(self.snapshot.blocked_by_deps)

    # -- rendering ---------------------------------------------------------- #

    def dashboard(self) -> str:
        proj = self.snapshot.project.name or "(unknown)"
        tag = f" — {self.snapshot.project.tagline}" if self.snapshot.project.tagline else ""
        rec = self.memory.recovery_summary()
        recs = []
        for i, pt in enumerate(self.plan[:3], 1):
            band = difficulty_band(pt.card.difficulty)
            recs.append(f"{i}. [{pt.priority}] {pt.card.title}  "
                        f"(difficulty {pt.card.difficulty}/10 {band} → "
                        f"{pt.card.recommended_model or '?'})")
        if not recs:
            recs.append("  (no tasks — nothing to dispatch)")
        return BANNER.format(
            project=f"{proj}{tag}",
            status=f"{self._completion()}% complete · {self._open_count()} open · "
                   f"{self._blocked_count()} blocked",
            memory=rec,
            count=len(self.plan),
            recommended="\n".join(recs),
        )

    def _render_status(self) -> str:
        L = [self.dashboard().rstrip("\n>")]
        prs = self.snapshot.pull_requests
        if prs:
            L.append("")
            L.append("Pull Requests:")
            for pr in prs:
                rs = f" [{pr.review_status}]" if pr.review_status else ""
                L.append(f"  #{pr.number} {pr.title}{rs}")
        if self.snapshot.ci.state != "unknown":
            L.append(f"CI: {self.snapshot.ci.state}")
        if self.snapshot.issues:
            L.append(f"Issues: {len(self.snapshot.issues)} open")
        return "\n".join(L)

    def _render_plan(self) -> str:
        if not self.plan:
            return "(no planned tasks)"
        L = ["Available tasks:"]
        for i, pt in enumerate(self.plan, 1):
            band = difficulty_band(pt.card.difficulty)
            L.append(f"  {i}. [{pt.priority:<6}] {pt.card.title}")
            L.append(f"     difficulty {pt.card.difficulty}/10 {band} → "
                     f"{pt.card.recommended_model or '?'} · {pt.reason}")
        return "\n".join(L)

    # -- commands ----------------------------------------------------------- #

    def handle(self, raw: str) -> str:
        parts = raw.strip().split()
        if not parts:
            return ""
        cmd, *args = parts
        c = cmd.lower()

        if c in ("status", "s", "st"):
            return self._render_status()

        if c in ("tasks", "t", "list", "plan", "p"):
            return self._render_plan()

        if c in ("show", "card"):
            return self._show(args)

        if c in ("dispatch", "d"):
            return self._dispatch(args, dry_run=True)

        if c in ("run", "exec"):
            return self._dispatch(args, dry_run=False)

        if c in ("focus", "f"):
            self.memory.save_focus({
                **self.memory.load_focus(),
                "current_focus": " ".join(args) if args else "",
            })
            return f"focus set: {' '.join(args) if args else '(cleared)'}"

        if c in ("recover", "r", "memory"):
            return "Memory: " + self.memory.recovery_summary()

        if c in ("envelope", "env"):
            return self._envelope(args)

        if c in ("team",):
            return self._team()

        if c in ("mine",):
            return self._mine()

        if c in ("claim",):
            return self._claim(args)

        if c in ("release",):
            return self._release(args)

        if c in ("done", "complete"):
            return self._done(args)

        if c in ("sync",):
            return self._sync()

        if c in ("dispatch-team", "dt", "dm"):
            return self._dispatch_team(args, dry_run=True)

        if c in ("run-team", "rt", "rm"):
            return self._dispatch_team(args, dry_run=False)

        if c in ("agents", "who"):
            found = available_agents()
            return "Worker agents: " + (", ".join(found) if found else "(none installed)")

        if c in ("models", "pool"):
            return "Model pool:\n" + "\n".join(
                f"  {k:<8} {', '.join(v)}" for k, v in self.pool.items()
            )

        if c in ("help", "h", "?"):
            return self._help()

        if c in ("quit", "q", "exit", "bye"):
            self.memory.touch_session()
            return "__QUIT__"

        return f"unknown command: {raw!r} (try 'help')"

    def _show(self, args: List[str]) -> str:
        idx = self._parse_index(args)
        if idx is None:
            return "usage: show <n>"
        return self.plan[idx].card.render()

    def _envelope(self, args: List[str]) -> str:
        """Render an AECP Task Envelope for a planned task (TaskCard → Envelope)."""
        from .envelope import build_envelope
        idx = self._parse_index(args)
        if idx is None:
            return "usage: envelope <n>"
        card = self.plan[idx].card
        if not card.recommended_model:
            route_card(card, self.pool)
        return build_envelope(card, self.repo)

    def _dispatch(self, args: List[str], dry_run: bool) -> str:
        idx = self._parse_index(args)
        if idx is None:
            return f"usage: {'dispatch' if dry_run else 'run'} <n> [target]"
        target = args[1] if len(args) > 1 else self._default_target()
        pt = self.plan[idx]
        card: TaskCard = pt.card
        if not card.recommended_model:
            route_card(card, self.pool)
        result = dispatch(card, target, self.repo, dry_run=dry_run)
        self._remember_dispatch(card, target)
        header = f"Dispatching '{card.title}' → [{target}]"
        if dry_run:
            return f"{header} (dry-run):\n  {result}"
        return f"{header}:\n{result}"

    def _default_target(self) -> str:
        agents = available_agents()
        return agents[0] if agents else "api"

    def _parse_index(self, args: List[str]) -> Optional[int]:
        if not args:
            return None
        try:
            n = int(args[0])
        except ValueError:
            return None
        if 1 <= n <= len(self.plan):
            return n - 1
        return None

    def _remember_dispatch(self, card: TaskCard, target: str) -> None:
        focus = self.memory.load_focus()
        focus["unfinished_tasks"] = [
            t for t in focus.get("unfinished_tasks", []) if t != card.title
        ]
        focus["unfinished_tasks"].insert(0, card.title)
        focus["unfinished_tasks"] = focus["unfinished_tasks"][:10]
        self.memory.save_focus(focus)

        tasks = self.memory.load_tasks()
        tasks[card.task_id] = {
            "title": card.title,
            "target": target,
            "model": card.recommended_model,
            "difficulty": card.difficulty,
        }
        self.memory.save_tasks(tasks)

    # -- hub commands ------------------------------------------------------ #

    def _hub_required(self) -> Optional[HubClient]:
        return self.hub

    def _hub_help(self) -> str:
        return "no hub configured — set AEW_HUB_URL (plus AEW_HUB_TOKEN / AEW_USER)"

    def _team(self) -> str:
        hub = self._hub_required()
        if hub is None:
            return self._hub_help()
        try:
            tasks = hub.tasks()
        except Exception as e:
            return f"hub error: {e}"
        groups = {"READY": [], "CLAIMED": [], "BLOCKED": [], "DONE": []}
        for t in tasks:
            groups.setdefault(t.get("status", "READY"), []).append(t)
        L = [f"AEW Hub · {hub.url}"]
        if not tasks:
            L.append("  (no tasks — try 'sync')")
        for st in ("READY", "CLAIMED", "BLOCKED", "DONE"):
            items = groups.get(st, [])
            L.append(f"\n{st}" + (f" ({len(items)})" if items else ""))
            for t in items:
                owner = f"  · {t.get('owner')}" if t.get("owner") else ""
                L.append(f"  {t.get('task_id', '?'):<14} {t.get('title', '')}{owner}")
        return "\n".join(L)

    def _mine(self) -> str:
        hub = self._hub_required()
        if hub is None:
            return self._hub_help()
        try:
            self.team_cards = hub.my_cards(self.user)
        except Exception as e:
            return f"hub error: {e}"
        if not self.team_cards:
            return "you have no claimed tasks"
        L = ["Your claimed tasks:"]
        for i, c in enumerate(self.team_cards, 1):
            L.append(f"  {i}. {c.task_id}")
            L.append(f"     difficulty {c.difficulty}/10 · recommended model: {c.recommended_model or '?'}")
        L.append("dispatch with: dispatch-team <n> [target]")
        return "\n".join(L)

    def _claim(self, args: List[str]) -> str:
        hub = self._hub_required()
        if hub is None:
            return self._hub_help()
        if not args:
            return "usage: claim <task_id>"
        try:
            r = hub.claim(args[0], self.user)
        except Exception as e:
            return f"hub error: {e}"
        if r.get("ok"):
            return f"CLAIMED ✓\n{r.get('task_id')} → {r.get('owner')} [{r.get('status')}]"
        return f"CLAIM FAILED — {r.get('message') or 'unknown'}"

    def _release(self, args: List[str]) -> str:
        hub = self._hub_required()
        if hub is None:
            return self._hub_help()
        if not args:
            return "usage: release <task_id>"
        try:
            r = hub.release(args[0], self.user)
        except Exception as e:
            return f"hub error: {e}"
        if r.get("ok"):
            return f"RELEASED ✓\n{r.get('task_id')} → [{r.get('status')}]"
        return f"RELEASE FAILED — {r.get('message') or 'unknown'}"

    def _done(self, args: List[str]) -> str:
        hub = self._hub_required()
        if hub is None:
            return self._hub_help()
        if not args:
            return "usage: done <task_id>"
        try:
            r = hub.done(args[0], self.user)
        except Exception as e:
            return f"hub error: {e}"
        if r.get("ok"):
            return f"DONE ✓\n{r.get('task_id')} → [{r.get('status')}]"
        return f"DONE FAILED — {r.get('message') or 'unknown'}"

    def _sync(self) -> str:
        hub = self._hub_required()
        if hub is None:
            return self._hub_help()
        try:
            r = hub.refresh()
        except Exception as e:
            return f"hub error: {e}"
        return (f"synced: {r.get('upserted', 0)} new/updated · "
                f"{r.get('total', 0)} team tasks · project {r.get('project', '?')}")

    def _dispatch_team(self, args: List[str], dry_run: bool) -> str:
        if not self.team_cards:
            return "no claimed tasks — run 'mine' first"
        verb = "dispatch-team" if dry_run else "run-team"
        if not args:
            return f"usage: {verb} <n> [target]"
        try:
            n = int(args[0])
        except ValueError:
            return f"usage: {verb} <n> [target]"
        if not 1 <= n <= len(self.team_cards):
            return f"no team task #{n} (have {len(self.team_cards)})"
        target = args[1] if len(args) > 1 else self._default_target()
        card = self.team_cards[n - 1]
        if not card.recommended_model:
            route_card(card, self.pool)
        result = dispatch(card, target, self.repo, dry_run=dry_run)
        self._remember_dispatch(card, target)
        header = f"Dispatching team task '{card.title}' → [{target}]"
        if dry_run:
            return f"{header} (dry-run):\n  {result}"
        return f"{header}:\n{result}"

    def _help(self) -> str:
        return (
            "commands:\n"
            "  status | s           current project dashboard\n"
            "  tasks  | plan        list planned tasks (difficulty + model)\n"
            "  show <n>             full task card\n"
            "  envelope <n>         AECP Task Envelope (TaskCard → tasks/GH-N.yaml)\n"
            "  dispatch <n> [tgt]   print the dispatch command (dry-run)\n"
            "  run <n> [tgt]        actually dispatch to a worker agent\n"
            "  focus <text>         set the current focus (persisted)\n"
            "  recover              what the last session left behind\n"
            "  agents               worker agents installed on this machine\n"
            "  models               the model pool\n"
            "  team                 team task board (from the hub)\n"
            "  mine                 your claimed tasks\n"
            "  claim <id>           claim a team task\n"
            "  release <id>         release a claimed task\n"
            "  done <id>            mark a claimed task DONE\n"
            "  sync                 refresh the hub from the repo\n"
            "  dispatch-team <n>    dispatch a claimed team task (dry-run)\n"
            "  run-team <n> [tgt]   actually dispatch a claimed team task\n"
            "  quit                 save memory and exit"
        )

    # -- loop --------------------------------------------------------------- #

    def run(self) -> int:
        print(self._render_status())
        self.memory.touch_session()
        while True:
            try:
                raw = input("> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            out = self.handle(raw)
            if out == "__QUIT__":
                break
            if out:
                print(out)
        return 0


def run_agent(repo: str, github: bool = False) -> int:
    return TerminalAgent(repo, github=github).run()
