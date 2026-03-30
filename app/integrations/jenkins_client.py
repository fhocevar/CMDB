from __future__ import annotations

from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from app.core.config import settings


class JenkinsClient:
    def __init__(self) -> None:
        self.base_url = str(settings.JENKINS_URL).rstrip("/")
        self.user = getattr(settings, "JENKINS_USER", None)
        self.password = getattr(settings, "JENKINS_PASSWORD", None)
        self.verify_tls = getattr(settings, "JENKINS_VERIFY_TLS", True)

        configured_timeout = getattr(settings, "JENKINS_TIMEOUT_SECONDS", 60)
        try:
            self.timeout = int(configured_timeout or 60)
        except Exception:
            self.timeout = 60

        self.session = requests.Session()
        self.session.verify = self.verify_tls

        if self.user and self.password:
            self.session.auth = HTTPBasicAuth(self.user, self.password)

        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "cmdb-capacity/1.0",
            }
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(
            self._url(path),
            params=params or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def list_computers(self) -> list[dict[str, Any]]:
        """
        Mantém a chamada leve para evitar timeout.
        """
        payload = self._get_json(
            "/computer/api/json",
            params={
                "tree": (
                    "computer[displayName,offline,temporarilyOffline,description,"
                    "numExecutors,busyExecutors,idleExecutors,assignedLabels[name],"
                    "monitorData[*]]"
                ),
                "depth": 1,
            },
        )

        computers = payload.get("computer", [])
        if not isinstance(computers, list):
            return []
        return computers

    def get_queue(self) -> list[dict[str, Any]]:
        payload = self._get_json(
            "/queue/api/json",
            params={
                "tree": "items[id,task[name],blocked,buildable,stuck,inQueueSince,why]",
                "depth": 1,
            },
        )
        items = payload.get("items", [])
        if not isinstance(items, list):
            return []
        return items