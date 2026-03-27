import httpx

from app.core.config import settings


class JenkinsClient:
    def __init__(self):
        self.base_url = settings.JENKINS_URL.rstrip("/")
        self.auth = (settings.JENKINS_USER, settings.JENKINS_PASSWORD)
        self.verify = settings.JENKINS_VERIFY_TLS

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"

        with httpx.Client(
            auth=self.auth,
            verify=self.verify,
            timeout=60.0,
        ) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    def list_computers(self) -> list[dict]:
        data = self._get(
            "/computer/api/json",
            params={
                "tree": (
                    "computer["
                    "displayName,"
                    "offline,"
                    "temporarilyOffline,"
                    "numExecutors,"
                    "busyExecutors,"
                    "idleExecutors,"
                    "assignedLabels[name],"
                    "monitorData,"
                    "description"
                    "]"
                )
            },
        )
        return data.get("computer", [])

    def get_queue(self) -> list[dict]:
        data = self._get(
            "/queue/api/json",
            params={
                "tree": (
                    "items["
                    "id,"
                    "blocked,"
                    "buildable,"
                    "stuck,"
                    "inQueueSince,"
                    "task[name,url]"
                    "]"
                )
            },
        )
        return data.get("items", [])