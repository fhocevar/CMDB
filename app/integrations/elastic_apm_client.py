import httpx

from app.core.config import settings


class ElasticApmClient:
    def __init__(self):
        self.base_url = settings.ELASTIC_APM_BASE_URL.rstrip("/")
        self.auth = None

        if settings.ELASTIC_APM_USER and settings.ELASTIC_APM_PASSWORD:
            self.auth = (settings.ELASTIC_APM_USER, settings.ELASTIC_APM_PASSWORD)

        self.verify = settings.ELASTIC_APM_VERIFY_TLS

    def get_services(self) -> dict:
        """
        Ajustar quando soubermos o endpoint real.
        Exemplos possíveis:
        - Kibana API
        - Elasticsearch API
        """
        with httpx.Client(auth=self.auth, verify=self.verify, timeout=60.0) as client:
            response = client.get(f"{self.base_url}/api/apm/services")
            response.raise_for_status()
            return response.json()