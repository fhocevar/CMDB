from datetime import datetime
import json

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


def _get(url: str) -> dict:
    response = requests.get(
        url,
        headers=_headers(),
        timeout=30,
        verify=settings.KUBERNETES_VERIFY_TLS,
    )
    response.raise_for_status()
    return response.json()


def _cpu_to_cores(cpu_raw: str) -> float:
    if not cpu_raw:
        return 0.0

    cpu_raw = str(cpu_raw).strip()

    if cpu_raw.endswith("n"):
        return float(cpu_raw[:-1]) / 1_000_000_000
    if cpu_raw.endswith("u"):
        return float(cpu_raw[:-1]) / 1_000_000
    if cpu_raw.endswith("m"):
        return float(cpu_raw[:-1]) / 1000

    return float(cpu_raw)


def _memory_to_bytes(mem_raw: str) -> float:
    if not mem_raw:
        return 0.0

    mem_raw = str(mem_raw).strip()

    factors = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
    }

    for suffix, factor in factors.items():
        if mem_raw.endswith(suffix):
            return float(mem_raw[:-len(suffix)]) * factor

    return float(mem_raw)


def _bytes_to_mb(value: float) -> float:
    return round(value / (1024 * 1024), 2)


def _bytes_to_gb(value: float) -> float:
    return round(value / (1024 * 1024 * 1024), 2)


def _safe_percent(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _extract_node_condition_status(node: dict) -> bool:
    conditions = node.get("status", {}).get("conditions", [])
    for condition in conditions:
        if condition.get("type") == "Ready":
            return condition.get("status") == "True"
    return False


def collect_from_kubernetes(db: Session) -> dict:
    if not settings.KUBERNETES_ENABLED:
        return {
            "status": "SKIPPED",
            "integration": "KUBERNETES",
            "reason": "KUBERNETES_ENABLED=false",
        }

    if not settings.KUBERNETES_API_URL:
        return {
            "status": "SKIPPED",
            "integration": "KUBERNETES",
            "reason": "KUBERNETES_API_URL não configurada",
        }

    base = settings.KUBERNETES_API_URL.rstrip("/")

    # API principal do cluster
    core_nodes = _get(f"{base}/api/v1/nodes")
    core_pods = _get(f"{base}/api/v1/pods")

    # Metrics Server
    metrics_nodes = _get(f"{base}/apis/metrics.k8s.io/v1beta1/nodes")
    metrics_pods = _get(f"{base}/apis/metrics.k8s.io/v1beta1/pods")

    node_specs = {item["metadata"]["name"]: item for item in core_nodes.get("items", [])}
    node_metrics = {item["metadata"]["name"]: item for item in metrics_nodes.get("items", [])}

    pod_specs = {
        (item["metadata"]["namespace"], item["metadata"]["name"]): item
        for item in core_pods.get("items", [])
    }
    pod_metrics = {
        (item["metadata"]["namespace"], item["metadata"]["name"]): item
        for item in metrics_pods.get("items", [])
    }

    now = datetime.utcnow()

    total_nodes = 0
    total_pods = 0
    metrics_written = 0

    # =========================
    # NODES
    # =========================
    for node_name, spec in node_specs.items():
        metric_item = node_metrics.get(node_name)
        if not metric_item:
            continue

        labels = spec.get("metadata", {}).get("labels", {})
        capacity = spec.get("status", {}).get("capacity", {})
        allocatable = spec.get("status", {}).get("allocatable", {})

        cpu_capacity_cores = _cpu_to_cores(capacity.get("cpu", "0"))
        memory_capacity_bytes = _memory_to_bytes(capacity.get("memory", "0"))

        cpu_allocatable_cores = _cpu_to_cores(allocatable.get("cpu", "0")) or cpu_capacity_cores
        memory_allocatable_bytes = _memory_to_bytes(allocatable.get("memory", "0")) or memory_capacity_bytes

        cpu_used_cores = _cpu_to_cores(metric_item.get("usage", {}).get("cpu", "0"))
        memory_used_bytes = _memory_to_bytes(metric_item.get("usage", {}).get("memory", "0"))

        cpu_percent = _safe_percent(cpu_used_cores, cpu_allocatable_cores)
        memory_percent = _safe_percent(memory_used_bytes, memory_allocatable_bytes)

        os_image = spec.get("status", {}).get("nodeInfo", {}).get("osImage")
        internal_ip = None
        for address in spec.get("status", {}).get("addresses", []):
            if address.get("type") == "InternalIP":
                internal_ip = address.get("address")
                break

        labels_json = json.dumps(labels, ensure_ascii=False)
        is_ready = _extract_node_condition_status(spec)

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=node_name,
                asset_type="K8S_NODE",
                environment="PRD",
                criticality="CRITICA",
                business_service="KUBERNETES",
                ip_address=internal_ip,
                operating_system=os_image or "LINUX",
                cpu_cores=max(int(round(cpu_allocatable_cores)), 1),
                memory_gb=max(_bytes_to_gb(memory_allocatable_bytes), 1),
                disk_gb=1,
                network_mbps=1000,
                cluster_name=settings.KUBERNETES_CLUSTER_NAME,
                namespace=None,
                source="KUBERNETES",
                provider="AKS",
                external_id=node_name,
                labels_json=labels_json,
                is_active=is_ready,
            ),
        )

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="cpu_percent",
                metric_value=cpu_percent,
                metric_unit="percent",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "cpu_percent")
        metrics_written += 1

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="memory_percent",
                metric_value=memory_percent,
                metric_unit="percent",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "memory_percent")
        metrics_written += 1

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="memory_mb_used",
                metric_value=_bytes_to_mb(memory_used_bytes),
                metric_unit="mb",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "memory_mb_used")
        metrics_written += 1

        total_nodes += 1

    # =========================
    # PODS
    # =========================
    for (namespace, pod_name), metric_item in pod_metrics.items():
        spec = pod_specs.get((namespace, pod_name))
        if not spec:
            continue

        pod_containers_metrics = metric_item.get("containers", [])
        pod_containers_spec = spec.get("spec", {}).get("containers", [])

        total_cpu_used_cores = 0.0
        total_memory_used_bytes = 0.0
        total_cpu_limit_cores = 0.0
        total_memory_limit_bytes = 0.0
        total_cpu_request_cores = 0.0
        total_memory_request_bytes = 0.0

        for container_metric in pod_containers_metrics:
            usage = container_metric.get("usage", {})
            total_cpu_used_cores += _cpu_to_cores(usage.get("cpu", "0"))
            total_memory_used_bytes += _memory_to_bytes(usage.get("memory", "0"))

        for container_spec in pod_containers_spec:
            resources = container_spec.get("resources", {})
            limits = resources.get("limits", {})
            requests_ = resources.get("requests", {})

            total_cpu_limit_cores += _cpu_to_cores(limits.get("cpu", "0"))
            total_memory_limit_bytes += _memory_to_bytes(limits.get("memory", "0"))
            total_cpu_request_cores += _cpu_to_cores(requests_.get("cpu", "0"))
            total_memory_request_bytes += _memory_to_bytes(requests_.get("memory", "0"))

        cpu_reference = total_cpu_limit_cores or total_cpu_request_cores
        memory_reference = total_memory_limit_bytes or total_memory_request_bytes

        cpu_percent = _safe_percent(total_cpu_used_cores, cpu_reference)
        memory_percent = _safe_percent(total_memory_used_bytes, memory_reference)

        node_name = spec.get("spec", {}).get("nodeName")
        phase = spec.get("status", {}).get("phase", "Unknown")
        labels = spec.get("metadata", {}).get("labels", {})
        labels_json = json.dumps(labels, ensure_ascii=False)

        business_service = namespace.upper()
        if namespace in settings.critical_apps:
            criticality = "CRITICA"
        else:
            criticality = "ALTA"

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=f"{namespace}-{pod_name}",
                asset_type="K8S_POD",
                environment="PRD",
                criticality=criticality,
                business_service=business_service,
                ip_address=spec.get("status", {}).get("podIP"),
                operating_system="CONTAINER",
                cpu_cores=max(int(round(cpu_reference or 1)), 1),
                memory_gb=max(_bytes_to_gb(memory_reference or (1024**3)), 1),
                disk_gb=1,
                network_mbps=1000,
                cluster_name=settings.KUBERNETES_CLUSTER_NAME,
                namespace=namespace,
                source="KUBERNETES",
                provider="AKS",
                external_id=f"{namespace}/{pod_name}",
                labels_json=labels_json,
                is_active=(phase == "Running"),
            ),
        )

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="cpu_percent",
                metric_value=cpu_percent,
                metric_unit="percent",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "cpu_percent")
        metrics_written += 1

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="memory_percent",
                metric_value=memory_percent,
                metric_unit="percent",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "memory_percent")
        metrics_written += 1

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="memory_mb_used",
                metric_value=_bytes_to_mb(total_memory_used_bytes),
                metric_unit="mb",
                collected_at=now,
                source="KUBERNETES",
            ),
        )
        update_baseline(db, asset.id, "memory_mb_used")
        metrics_written += 1

        total_pods += 1

    return {
        "status": "OK",
        "integration": "KUBERNETES",
        "cluster_name": settings.KUBERNETES_CLUSTER_NAME,
        "nodes_collected": total_nodes,
        "pods_collected": total_pods,
        "metrics_written": metrics_written,
    }