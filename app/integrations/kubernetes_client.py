from datetime import datetime

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def _headers() -> dict:
    headers = {}
    if settings.KUBERNETES_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {settings.KUBERNETES_BEARER_TOKEN}"
    return headers


def _parse_cpu_to_percent(cpu_raw: str) -> float:
    if cpu_raw.endswith("n"):
        nano = float(cpu_raw[:-1])
        return round(nano / 10_000_000, 4)
    if cpu_raw.endswith("m"):
        milli = float(cpu_raw[:-1])
        return round(milli / 10, 4)
    return float(cpu_raw)


def _parse_memory_to_mb(mem_raw: str) -> float:
    if mem_raw.endswith("Ki"):
        return round(float(mem_raw[:-2]) / 1024, 2)
    if mem_raw.endswith("Mi"):
        return round(float(mem_raw[:-2]), 2)
    if mem_raw.endswith("Gi"):
        return round(float(mem_raw[:-2]) * 1024, 2)
    return float(mem_raw)


def collect_from_kubernetes(db: Session) -> None:
    if not settings.KUBERNETES_API_URL:
        return

    base = settings.KUBERNETES_API_URL.rstrip("/")
    headers = _headers()
    verify = settings.KUBERNETES_VERIFY_TLS

    nodes_resp = requests.get(
        f"{base}/apis/metrics.k8s.io/v1beta1/nodes",
        headers=headers,
        timeout=20,
        verify=verify,
    )
    nodes_resp.raise_for_status()
    nodes = nodes_resp.json().get("items", [])

    for node in nodes:
        node_name = node["metadata"]["name"]
        cpu_raw = node["usage"]["cpu"]
        mem_raw = node["usage"]["memory"]

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=node_name,
                asset_type="K8S_NODE",
                environment="PRD",
                criticality="CRITICA",
                business_service="KUBERNETES",
                operating_system="LINUX",
                cpu_cores=1,
                memory_gb=1,
                disk_gb=1,
                network_mbps=1000,
                source="KUBERNETES",
                provider="K8S",
                external_id=node_name,
            ),
        )

        now = datetime.utcnow()

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="cpu_percent",
                metric_value=_parse_cpu_to_percent(cpu_raw),
                metric_unit="percent",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "cpu_percent")

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="memory_mb_used",
                metric_value=_parse_memory_to_mb(mem_raw),
                metric_unit="mb",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "memory_mb_used")

    pods_resp = requests.get(
        f"{base}/apis/metrics.k8s.io/v1beta1/pods",
        headers=headers,
        timeout=20,
        verify=verify,
    )
    pods_resp.raise_for_status()
    pods = pods_resp.json().get("items", [])

    for pod in pods:
        pod_name = pod["metadata"]["name"]
        namespace = pod["metadata"]["namespace"]

        total_cpu = 0.0
        total_mem_mb = 0.0

        for container in pod.get("containers", []):
            total_cpu += _parse_cpu_to_percent(container["usage"]["cpu"])
            total_mem_mb += _parse_memory_to_mb(container["usage"]["memory"])

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=f"{namespace}-{pod_name}",
                asset_type="K8S_POD",
                environment="PRD",
                criticality="ALTA",
                business_service=namespace.upper(),
                operating_system="CONTAINER",
                cpu_cores=1,
                memory_gb=1,
                disk_gb=1,
                network_mbps=1000,
                cluster_name="k8s",
                namespace=namespace,
                source="KUBERNETES",
                provider="K8S",
                external_id=f"{namespace}/{pod_name}",
            ),
        )

        now = datetime.utcnow()

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="cpu_percent",
                metric_value=round(total_cpu, 2),
                metric_unit="percent",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "cpu_percent")

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="memory_mb_used",
                metric_value=round(total_mem_mb, 2),
                metric_unit="mb",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "memory_mb_used")
