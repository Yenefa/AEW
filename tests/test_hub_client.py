"""Tests for the Hub client + team-task-to-card bridge."""

import os
import unittest

from aew.hub.models import CLAIMED, TeamTask, team_task_to_card
from aew.hub_client import HubClient


class TestTeamTaskToCard(unittest.TestCase):
    def test_conversion(self):
        tt = TeamTask(task_id="AEDL-W4A", title="Implement W4A", source="native",
                      status=CLAIMED, owner="Maple", difficulty=6,
                      recommended_model="glm-5.3")
        c = team_task_to_card(tt)
        self.assertEqual(c.task_id, "AEDL-W4A")
        self.assertEqual(c.title, "Implement W4A")
        self.assertEqual(c.difficulty, 6)
        self.assertEqual(c.recommended_model, "glm-5.3")
        self.assertIn("RESULT CARD", c.acceptance[0])
        self.assertEqual(c.project, "AEDL")

    def test_pr_card_has_no_project_hint(self):
        tt = TeamTask(task_id="GH-PR-42", title="Review PR #42", source="pr",
                      status=CLAIMED, difficulty=2)
        c = team_task_to_card(tt)
        self.assertEqual(c.project, "")


class TestHubClientFromEnv(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("AEW_HUB_URL", "AEW_HUB_TOKEN", "AEW_USER")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_none_without_url(self):
        for k in ("AEW_HUB_URL", "AEW_HUB_TOKEN", "AEW_USER"):
            os.environ.pop(k, None)
        self.assertIsNone(HubClient.from_env())

    def test_configured(self):
        os.environ["AEW_HUB_URL"] = "http://100.64.0.1:8765"
        os.environ["AEW_HUB_TOKEN"] = "tok"
        os.environ["AEW_USER"] = "Maple"
        c = HubClient.from_env()
        self.assertEqual(c.url, "http://100.64.0.1:8765")
        self.assertEqual(c.user, "Maple")
        self.assertEqual(c.token, "tok")


if __name__ == "__main__":
    unittest.main()
