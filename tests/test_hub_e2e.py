"""End-to-end Hub test — two clients over a real HTTP socket.

This maps directly to the MVP acceptance criteria: two people can read the same
team snapshot, a claim by A is visible to B, concurrent claims yield one winner,
and a claimed task converts into a dispatchable local TaskCard.

Each test runs against its own fresh Hub (setUp/tearDown) so there is no
ordering coupling between tests.
"""

import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from aew.dispatch import dispatch
from aew.hub.api import HubApp, _Handler
from aew.hub.coordinator import Coordinator
from aew.hub.store import Store
from aew.hub_client import HubClient

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_project"


class TestHubE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = Store(Path(self.tmp.name) / "hub.db")
        coord = Coordinator(store, SAMPLE, github=False)
        coord.refresh()
        app = HubApp(coord, token="tok")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.app = app
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.port}"
        self.maple = HubClient(base, "tok", "Maple")
        self.ryan = HubClient(base, "tok", "Ryan")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def _ready_task_id(self):
        ready = [t for t in self.maple.tasks() if t["status"] == "READY"]
        self.assertTrue(ready, "expected at least one READY team task")
        return ready[0]["task_id"]

    def test_health(self):
        self.assertTrue(self.maple.health()["ok"])

    def test_two_clients_read_same_snapshot(self):
        self.assertEqual(self.maple.snapshot()["counts"],
                         self.ryan.snapshot()["counts"])

    def test_claim_visible_to_other(self):
        tid = self._ready_task_id()
        self.assertTrue(self.maple.claim(tid)["ok"])
        board = {t["task_id"]: t for t in self.ryan.tasks()}
        self.assertEqual(board[tid]["owner"], "Maple")
        self.assertEqual(board[tid]["status"], "CLAIMED")

    def test_concurrent_claim_single_winner(self):
        tid = self._ready_task_id()
        results = []
        barrier = threading.Barrier(2)

        def go(client):
            barrier.wait()
            try:
                results.append(client.claim(tid))
            except Exception as e:
                results.append({"ok": False, "error": str(e)})

        t1 = threading.Thread(target=go, args=(self.maple,))
        t2 = threading.Thread(target=go, args=(self.ryan,))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(sum(1 for r in results if r.get("ok")), 1)

    def test_claimed_task_becomes_dispatchable_card(self):
        tid = self._ready_task_id()
        self.maple.claim(tid)
        cards = self.maple.my_cards()
        self.assertIn(tid, [c.task_id for c in cards])
        card = next(c for c in cards if c.task_id == tid)
        out = dispatch(card, "api", SAMPLE, dry_run=True)
        self.assertIn(tid, out)
        self.assertIn("difficulty", out)


if __name__ == "__main__":
    unittest.main()
