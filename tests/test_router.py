"""Tests for the Model Router + Cost Ledger (v1)."""

import tempfile
import unittest
from pathlib import Path

from aew.model import TaskCard
from aew.router import (
    DEFAULT_MODEL_POOL,
    CostLedger,
    load_model_pool,
    route,
    route_card,
)


class TestRoute(unittest.TestCase):
    def test_simple_goes_cheap(self):
        self.assertEqual(route(2), DEFAULT_MODEL_POOL["cheap"][0])

    def test_standard_goes_mid(self):
        self.assertEqual(route(5), DEFAULT_MODEL_POOL["mid"][0])

    def test_architectural_goes_strong(self):
        self.assertEqual(route(9), DEFAULT_MODEL_POOL["strong"][0])

    def test_vision_overrides_tier(self):
        self.assertEqual(route(9, need_image=True), DEFAULT_MODEL_POOL["vision"][0])

    def test_route_card_detects_vision(self):
        card = TaskCard(task_id="X", title="Analyze hardware schematic", difficulty=5)
        self.assertEqual(route_card(card), DEFAULT_MODEL_POOL["vision"][0])

    def test_route_card_sets_field(self):
        card = TaskCard(task_id="X", title="Fix parser", difficulty=2)
        route_card(card)
        self.assertEqual(card.recommended_model, DEFAULT_MODEL_POOL["cheap"][0])


class TestModelPool(unittest.TestCase):
    def test_default_pool_is_copy(self):
        pool = load_model_pool()
        self.assertIn("cheap", pool)
        pool["cheap"].append("x")
        self.assertNotIn("x", DEFAULT_MODEL_POOL["cheap"])

    def test_load_yaml_style_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "models.yaml"
            p.write_text("cheap:\n  - my-flash\nstrong:\n  - my-gpt\n", encoding="utf-8")
            pool = load_model_pool(p)
            self.assertEqual(pool["cheap"][0], "my-flash")
            self.assertEqual(pool["strong"][0], "my-gpt")

    def test_load_json_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "models.json"
            p.write_text('{"cheap": ["a"], "strong": ["b"]}', encoding="utf-8")
            pool = load_model_pool(p)
            self.assertEqual(pool["cheap"], ["a"])

    def test_missing_file_falls_back(self):
        pool = load_model_pool(Path("/nonexistent/models.yaml"))
        self.assertIn("cheap", pool)


class TestCostLedger(unittest.TestCase):
    def test_record_and_total(self):
        ledger = CostLedger()
        ledger.record("T1", "flash", 3, cost=0.01)
        ledger.record("T2", "gpt", 9, cost=0.30)
        self.assertEqual(ledger.total_cost(), 0.31)
        self.assertEqual(len(ledger.records), 2)

    def test_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "cost.json"
            ledger = CostLedger(path)
            ledger.record("T1", "flash", 3, cost=0.01)
            reloaded = CostLedger(path)
            self.assertEqual(reloaded.total_cost(), 0.01)


if __name__ == "__main__":
    unittest.main()
