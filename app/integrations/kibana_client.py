import httpx

from app.core.config import settings


class KibanaClient:
    def __init__(self):
        self.base_url = (settings.ELASTICSEARCH_URL or "").rstrip("/")
        self.verify = settings.ELASTICSEARCH_VERIFY_TLS
        self.auth = None

        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("ELASTICSEARCH_URL inválida. Informe com http:// ou https://")

        if settings.ELASTICSEARCH_USER and settings.ELASTICSEARCH_PASSWORD:
            self.auth = (settings.ELASTICSEARCH_USER, settings.ELASTICSEARCH_PASSWORD)

    def _get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"

        with httpx.Client(
            auth=self.auth,
            verify=self.verify,
            timeout=60.0,
            headers={"kbn-xsrf": "true"},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def get_status(self) -> dict:
        return self._get("/api/status")

    def list_data_views(self) -> dict:
        return self._get("/api/data_views")