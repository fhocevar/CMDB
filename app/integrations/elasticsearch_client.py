import httpx

from app.core.config import settings


class ElasticsearchClient:
    """
    Acesso ao Elasticsearch via proxy do Kibana (/api/console/proxy).
    """

    def __init__(self):
        self.base_url = (settings.KIBANA_URL or "").rstrip("/")
        self.verify = settings.KIBANA_VERIFY_TLS
        self.auth = None

        if self.base_url and not (
            self.base_url.startswith("http://") or self.base_url.startswith("https://")
        ):
            raise ValueError("KIBANA_URL inválida. Informe com http:// ou https://")

        if settings.KIBANA_USER and settings.KIBANA_PASSWORD:
            self.auth = (settings.KIBANA_USER, settings.KIBANA_PASSWORD)

    def _proxy(self, method: str, es_path: str, body: dict | None = None) -> dict:
        url = f"{self.base_url}/api/console/proxy"
        params = {
            "path": es_path,
            "method": method.upper(),
        }

        with httpx.Client(
            auth=self.auth,
            verify=self.verify,
            timeout=90.0,
            headers={"kbn-xsrf": "true"},
        ) as client:
            response = client.post(url, params=params, json=body or {})

            if response.status_code >= 400:
                detail = response.text.strip()
                raise RuntimeError(
                    f"Erro Elasticsearch via Kibana proxy ({response.status_code}): {detail}"
                )

            return response.json()

    def search(self, index_pattern: str, body: dict) -> dict:
        es_path = f"/{index_pattern}/_search?ignore_unavailable=true&allow_no_indices=true"
        return self._proxy("POST", es_path, body)

    def search_metrics_hosts(self) -> dict:
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"@timestamp": {"gte": "now-15m"}}},
                        {"exists": {"field": "host.name"}},
                    ]
                }
            },
            "aggs": {
                "by_host": {
                    "terms": {
                        "field": "host.name",
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
        return self.search("metrics-*", body)

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
                        "field": "kubernetes.pod.name",
                        "size": 100
                    },
                    "aggs": {
                        "cpu_avg": {"avg": {"field": "kubernetes.pod.cpu.usage.node.pct"}},
                        "namespace": {
                            "terms": {"field": "kubernetes.namespace", "size": 1}
                        }
                    }
                }
            }
        }
        return self.search("metrics-*", body)

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
                        "field": "container.name",
                        "size": 100
                    },
                    "aggs": {
                        "cpu_avg": {"avg": {"field": "docker.cpu.total.pct"}}
                    }
                }
            }
        }
        return self.search("metrics-*", body)