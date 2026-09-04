"""Tests for the Hub HTTP API — exercised through `HubApp.handle` (no socket)."""

import json
import tempfile
import unittest
from pathlib import Path

from aew.hub.api import HubApp
from aew.hub.coordinator import Coordinator
from aew.hub.models import READY, TeamTask
from aew.hub.store import Store


class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite")
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        self.coord = Coordinator(self.store, repo, github=False)
        self.app = HubApp(self.coord, token="secret")

    def tearDown(self):
        self.tmp.cleanup()

    def _req(self, method, path, body=None, token="secret"):
        headers = {"Authorization": f"Bearer {token}"}
        data = json.dumps(body).encode() if body is not None else b""
        return self.app.handle(method, path, data, headers)

    def _seed(self, task_id="AEDL-W4A"):
        self.store.upsert(TeamTask(task_id=task_id, title="x", source="native", status=READY))

    def test_health(self):
        st, payload = self._req("GET", "/health")
        self.assertEqual(st, 200)
        self.assertTrue(payload["ok"])

    def test_auth_required(self):
        st, _ = self._req("GET", "/health", token="wrong")
        self.assertEqual(st, 401)

    def test_claim_then_conflict(self):
        self._seed()
        st, p = self._req("POST", "/tasks/AEDL-W4A/claim", {"user": "Maple"})
        self.assertEqual(st, 200)
        self.assertTrue(p["ok"])
        self.assertEqual(p["status"], "CLAIMED")
        st2, p2 = self._req("POST", "/tasks/AEDL-W4A/claim", {"user": "Ryan"})
        self.assertEqual(st2, 409)
        self.assertFalse(p2["ok"])

    def test_release_and_done(self):
        self._seed()
        self._req("POST", "/tasks/AEDL-W4A/claim", {"user": "Maple"})
        st, p = self._req("POST", "/tasks/AEDL-W4A/release", {"user": "Maple"})
        self.assertEqual(st, 200)
        self.assertEqual(p["status"], "READY")
        self._req("POST", "/tasks/AEDL-W4A/claim", {"user": "Maple"})
        st, p = self._req("POST", "/tasks/AEDL-W4A/done", {"user": "Maple"})
        self.assertEqual(st, 200)
        self.assertEqual(p["status"], "DONE")

    def test_mine(self):
        self._seed("T1")
        self._req("POST", "/tasks/T1/claim", {"user": "Maple"})
        st, p = self._req("GET", "/tasks/mine?user=Maple")
        self.assertEqual(st, 200)
        self.assertEqual(len(p["tasks"]), 1)
        self.assertEqual(p["tasks"][0]["task_id"], "T1")

    def test_tasks_listing(self):
        self._seed()
        st, p = self._req("GET", "/tasks")
        self.assertEqual(st, 200)
        self.assertEqual(len(p["tasks"]), 1)

    def test_snapshot(self):
        self._seed()
        st, p = self._req("GET", "/snapshot")
        self.assertEqual(st, 200)
        self.assertIn("counts", p)

    def test_approve_is_never_an_endpoint(self):
        # Human-only: approval must come from the Hub CLI with interactive
        # confirm, never from an HTTP call a worker subprocess could make.
        self._seed()
        self._req("POST", "/tasks/AEDL-W4A/claim", {"user": "Maple"})
        st, p = self._req("POST", "/tasks/AEDL-W4A/approve", {"user": "Maple"})
        self.assertEqual(st, 403)
        self.assertFalse(p["ok"])

    def test_lease_and_promote_flow(self):
        self._seed()
        st, p = self._req("POST", "/tasks/AEDL-W4A/lease",
                          {"run_id": "run-001", "worker": "maple"})
        self.assertEqual(st, 200)
        self.assertEqual(p["status"], "EXECUTING")
        st, p = self._req("POST", "/tasks/AEDL-W4A/result",
                          {"run_id": "run-001", "summary": "ok",
                           "head_sha": "bf593f4", "gate_status": "pass"})
        self.assertEqual(p["status"], "PROPOSED")
        st, p = self._req("POST", "/tasks/AEDL-W4A/review", {"run_id": "run-001"})
        self.assertEqual(p["status"], "PENDING_HUMAN_REVIEW")
        st, p = self._req("POST", "/tasks/AEDL-W4A/promote", {"run_id": "run-001"})
        self.assertEqual(st, 409)   # promotion gate: needs APPROVED first
        self.assertIn("gate", p.get("reason", ""))

    def test_missing_user_rejected(self):
        self._seed()
        st, _ = self._req("POST", "/tasks/AEDL-W4A/claim", {})
        self.assertEqual(st, 400)

    def test_unknown_route_404(self):
        st, _ = self._req("GET", "/nope")
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
