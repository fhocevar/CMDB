import httpx

from app.core.config import settings


class ElasticsearchClient:
    def __init__(self):
        self.base_url = (settings.ELASTICSEARCH_URL or "").rstrip("/")
        self.verify = settings.ELASTICSEARCH_VERIFY_TLS
        self.auth = None

        if self.base_url and not (
            self.base_url.startswith("http://") or self.base_url.startswith("https://")
        ):
            raise ValueError(
                "ELASTICSEARCH_URL inválida. Informe com http:// ou https://"
            )

        if settings.ELASTICSEARCH_USER and settings.ELASTICSEARCH_PASSWORD:
            self.auth = (settings.ELASTICSEARCH_USER, settings.ELASTICSEARCH_PASSWORD)

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"

        with httpx.Client(
            auth=self.auth,
            verify=self.verify,
            timeout=60.0,
        ) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
            return response.json()

    def field_caps(self, index_pattern: str) -> dict:
        return self._post(
            f"/{index_pattern}/_field_caps?fields=*&ignore_unavailable=true&allow_no_indices=true",
            {},
        )

    def search(self, index_pattern: str, body: dict) -> dict:
        return self._post(
            f"/{index_pattern}/_search?ignore_unavailable=true&allow_no_indices=true",
            body,
        )

    def search_metrics_hosts(self) -> dict:
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"@timestamp": {"gte": "now-15m"}}},
                        {"exists": {"field": "host.name"}},
                        {"exists": {"field": "system.cpu.total.norm.pct"}},
                    ]
                }
            },
            "aggs": {
                "by_host": {
                    "terms": {
                        "field": "host.name.keyword",
                        "size": 100
                    },
                    "aggs": {
                        "cpu_avg": {"avg": {"field": "system.cpu.total.norm.pct"}},
                        "memory_avg": {"avg": {"field": "system.memory.actual.used.pct"}},
                        "disk_avg": {"avg": {"field": "system.filesystem.used.pct"}}
                    }
                }
            }
        }
        return self._post("/metrics-*/_search", body)

    def search_metrics_kubernetes_pods(self) -> dict:
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"@timestamp": {"gte": "now-15m"}}},
                        {"exists": {"field": "kubernetes.pod.name"}},
                    ]
                }
            },
            "aggs": {
                "by_pod": {
                    "terms": {
                        "field": "kubernetes.pod.name.keyword",
                        "size": 100
                    },
                    "aggs": {
                        "cpu_avg": {"avg": {"field": "kubernetes.pod.cpu.usage.node.pct"}},
                        "namespace": {
                            "terms": {"field": "kubernetes.namespace.keyword", "size": 1}
                        }
                    }
                }
            }
        }
        return self._post("/metrics-*/_search", body)

    def search_metrics_docker(self) -> dict:
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"@timestamp": {"gte": "now-15m"}}},
                        {"exists": {"field": "container.name"}},
                    ]
                }
            },
            "aggs": {
                "by_container": {
                    "terms": {
                        "field": "container.name.keyword",
                        "size": 100
                    },
                    "aggs": {
                        "cpu_avg": {"avg": {"field": "docker.cpu.total.pct"}}
                    }
                }
            }
        }
        return self._post("/metrics-*/_search", body)