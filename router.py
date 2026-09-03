"""Model Router — pick the right model for a task, and keep a cost ledger.

Deterministic, rule-based (same spirit as the DAG): difficulty tier + an explicit
"needs vision" signal decide the model. No LLM call is used to route — that would
be the tail wagging the dog.

The model pool is configurable. Default pool mirrors the proposal:

    cheap   -> z-ai/glm-5.3-flash, deepseek
    mid     -> z-ai/glm-5.3, gemini-pro      (standard 4-7 tier)
    vision  -> gemini-flash
    strong  -> claude, gpt
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .model import TaskCard
from .planner import difficulty_band

DEFAULT_MODEL_POOL: Dict[str, List[str]] = {
    "cheap": ["z-ai/glm-5.3-flash", "deepseek"],
    "mid": ["z-ai/glm-5.3", "gemini-pro"],
    "vision": ["gemini-flash"],
    "strong": ["claude", "gpt"],
}

_VISION_HINTS = ("image", "vision", "schematic", "hardware", "diagram", "photo")


def _parse_simple_yaml(text: str) -> Dict[str, List[str]]:
    """Parse the flat `key:` + `- item` YAML shown in the proposal. No dep."""
    pool: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not s.startswith("-") and ":" in s:
            current = s.split(":", 1)[0].strip()
            pool.setdefault(current, [])
        elif s.startswith("-") and current is not None:
            pool[current].append(s[1:].strip())
    return pool


def _copy_pool(pool: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Deep-copy the pool so callers can't mutate the shared default."""
    return {k: list(v) for k, v in pool.items()}


def load_model_pool(path: Optional[Path | str] = None) -> Dict[str, List[str]]:
    """Load the pool from a YAML/JSON file, falling back to the default pool."""
    if path is None:
        return _copy_pool(DEFAULT_MODEL_POOL)
    p = Path(path)
    if not p.exists():
        return _copy_pool(DEFAULT_MODEL_POOL)
    try:
        text = p.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            return {k: list(v) for k, v in data.items() if isinstance(v, list)}
    except Exception:
        pass
    try:
        pool = _parse_simple_yaml(p.read_text(encoding="utf-8"))
        return pool if pool else _copy_pool(DEFAULT_MODEL_POOL)
    except Exception:
        return _copy_pool(DEFAULT_MODEL_POOL)


def _first(pool: Dict[str, List[str]], key: str) -> str:
    return (pool.get(key) or [""])[0]


def route(difficulty: int, need_image: bool = False,
          pool: Optional[Dict[str, List[str]]] = None) -> str:
    """Return the recommended model name for a difficulty score."""
    pool = pool or DEFAULT_MODEL_POOL
    if need_image:
        return _first(pool, "vision")
    band = difficulty_band(difficulty)
    if band == "simple":
        return _first(pool, "cheap")
    if band == "architectural":
        return _first(pool, "strong")
    return _first(pool, "mid")


def _needs_image(card: TaskCard) -> bool:
    haystack = " ".join(
        [card.title, card.objective, " ".join(card.constraints), " ".join(card.files)]
    ).lower()
    return any(h in haystack for h in _VISION_HINTS)


def route_card(card: TaskCard, pool: Optional[Dict[str, List[str]]] = None) -> str:
    """Assign a model to a task card, honoring an explicit vision signal."""
    model = route(card.difficulty, need_image=_needs_image(card), pool=pool)
    card.recommended_model = model
    return model


# --------------------------------------------------------------------------- #
# Cost ledger                                                                  #

@dataclass
class CostRecord:
    task_id: str
    model: str
    difficulty: int
    estimated_tokens: int = 0
    cost: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class CostLedger:
    """Append-only cost log; reads/writes JSON, never raises on I/O errors."""

    def __init__(self, path: Optional[Path | str] = None):
        self.path = Path(path) if path else None
        self.records: List[CostRecord] = []
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data if isinstance(data, list) else []:
                self.records.append(CostRecord(
                    task_id=item.get("task_id", ""),
                    model=item.get("model", ""),
                    difficulty=item.get("difficulty", 0),
                    estimated_tokens=item.get("estimated_tokens", 0),
                    cost=item.get("cost", 0.0),
                    timestamp=item.get("timestamp", ""),
                ))
        except Exception:
            return

    def record(self, task_id: str, model: str, difficulty: int,
               estimated_tokens: int = 0, cost: float = 0.0) -> CostRecord:
        rec = CostRecord(task_id=task_id, model=model, difficulty=difficulty,
                         estimated_tokens=estimated_tokens, cost=cost)
        self.records.append(rec)
        self._flush()
        return rec

    def _flush(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps([r.__dict__ for r in self.records], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            return

    def total_cost(self) -> float:
        return round(sum(r.cost for r in self.records), 4)
