"""Hub client — a Local AEW talks to the Hub over HTTP (stdlib only).

Configuration via environment variables:

    AEW_HUB_URL    e.g. http://100.x.x.x:8765
    AEW_HUB_TOKEN  shared Bearer token
    AEW_USER       who I am (e.g. Maple / Ryan)

When AEW_HUB_URL is unset, `HubClient.from_env()` returns None and the Terminal
Agent's team commands degrade to a "no hub configured" message.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from .hub.models import TeamTask, team_task_to_card
from .model import TaskCard


class HubError(Exception):
    pass


class HubClient:
    def __init__(self, url: str, token: str = "", user: str = ""):
        self.url = url.rstrip("/")
        self.token = token
        self.user = user

    @classmethod
    def from_env(cls) -> Optional["HubClient"]:
        url = os.environ.get("AEW_HUB_URL", "").strip()
        if not url:
            return None
        return cls(
            url,
            os.environ.get("AEW_HUB_TOKEN", "").strip(),
            os.environ.get("AEW_USER", "").strip(),
        )

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        data = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
                raise HubError(payload.get("message") or payload.get("error") or f"HTTP {e.code}")
            except json.JSONDecodeError:
                raise HubError(f"HTTP {e.code}")
        except urllib.error.URLError as e:
            raise HubError(f"cannot reach hub: {e.reason}")

    def health(self) -> dict:
        return self._request("GET", "/health")

    def snapshot(self) -> dict:
        return self._request("GET", "/snapshot")

    def tasks(self) -> List[dict]:
        return self._request("GET", "/tasks").get("tasks", [])

    def mine(self, user: str = "") -> List[dict]:
        u = user or self.user
        return self._request("GET", f"/tasks/mine?user={u}").get("tasks", [])

    def refresh(self) -> dict:
        return self._request("POST", "/refresh", {})

    def _post(self, path: str, body: dict) -> dict:
        """POST that returns the parsed JSON dict even on 4xx (e.g. claim conflicts)."""
        data = json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                raise HubError(f"HTTP {e.code}")
        except urllib.error.URLError as e:
            raise HubError(f"cannot reach hub: {e.reason}")

    def claim(self, task_id: str, user: str = "") -> dict:
        return self._post(f"/tasks/{task_id}/claim", {"user": user or self.user})

    def release(self, task_id: str, user: str = "") -> dict:
        return self._post(f"/tasks/{task_id}/release", {"user": user or self.user})

    def done(self, task_id: str, user: str = "") -> dict:
        return self._post(f"/tasks/{task_id}/done", {"user": user or self.user})

    # -- run lease / promotion authority (v2.1; approve is CLI-only) -------- #

    def lease(self, task_id: str, run_id: str, worker: str = "",
              ttl_seconds: int = 3600) -> dict:
        return self._post(f"/tasks/{task_id}/lease",
                          {"run_id": run_id, "worker": worker or self.user,
                           "ttl_seconds": ttl_seconds})

    def submit_result(self, task_id: str, run_id: str, summary: str = "",
                      head_sha: str = "", gate_status: str = "") -> dict:
        return self._post(f"/tasks/{task_id}/result",
                          {"run_id": run_id, "summary": summary,
                           "head_sha": head_sha, "gate_status": gate_status})

    def request_review(self, task_id: str, run_id: str) -> dict:
        return self._post(f"/tasks/{task_id}/review", {"run_id": run_id})

    def promote(self, task_id: str, run_id: str) -> dict:
        return self._post(f"/tasks/{task_id}/promote", {"run_id": run_id})

    def my_cards(self, user: str = "") -> List[TaskCard]:
        return [team_task_to_card(TeamTask(**t)) for t in self.mine(user)]
