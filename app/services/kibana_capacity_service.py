from datetime import datetime
import json

from sqlalchemy.orm import Session

from app.integrations.elasticsearch_client import ElasticsearchClient
from app.integrations.kibana_client import KibanaClient
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def _normalize_pct(value) -> float:
    if value is None:
        return 0.0
    value = float(value)
    if value <= 1:
        value *= 100.0
    return round(value, 2)


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _status_from_usage(cpu_pct: float = 0.0, memory_pct: float = 0.0, disk_pct: float = 0.0) -> str:
    if cpu_pct >= 90 or memory_pct >= 92 or disk_pct >= 92:
        return "critical"
    if cpu_pct >= 80 or memory_pct >= 85 or disk_pct >= 85:
        return "warning"
    return "ok"


def collect_from_kibana(db: Session) -> dict:
    try:
        kibana = KibanaClient()
        es = ElasticsearchClient()

        status = kibana.get_status()
        data_views_payload = kibana.list_data_views()

        hosts_response = es.search_metrics_hosts()
        pods_response = es.search_metrics_kubernetes_pods()
        docker_response = es.search_metrics_docker()
    except Exception as exc:
        return {
            "status": "ERROR",
            "integration": "KIBANA",
            "message": str(exc),
        }

    collected_at = datetime.utcnow()
    metrics_written = 0

    views = data_views_payload.get("data_view", []) or data_views_payload.get("data_views", []) or []

    host_buckets = hosts_response.get("aggregations", {}).get("by_host", {}).get("buckets", [])
    pod_buckets = pods_response.get("aggregations", {}).get("by_pod", {}).get("buckets", [])
    docker_buckets = docker_response.get("aggregations", {}).get("by_container", {}).get("buckets", [])

    hosts_collected = 0
    pods_collected = 0
    containers_collected = 0

    hosts_high_cpu = 0
    hosts_high_memory = 0
    hosts_low_disk = 0

    host_cpu_values = []
    host_memory_values = []
    host_disk_values = []

    top_hosts = []
    top_pods = []
    top_containers = []

    for bucket in host_buckets:
        host_name = bucket.get("key")
        if not host_name:
            continue

        cpu_pct = _normalize_pct(bucket.get("cpu_avg", {}).get("value"))
        memory_pct = _normalize_pct(bucket.get("memory_avg", {}).get("value"))
        disk_pct = _normalize_pct(bucket.get("disk_avg", {}).get("value"))

        if cpu_pct > 0:
            host_cpu_values.append(cpu_pct)
        if memory_pct > 0:
            host_memory_values.append(memory_pct)
        if disk_pct > 0:
            host_disk_values.append(disk_pct)

        if cpu_pct >= 80:
            hosts_high_cpu += 1
        if memory_pct >= 85:
            hosts_high_memory += 1
        if disk_pct >= 85:
            hosts_low_disk += 1

        status_level = _status_from_usage(cpu_pct, memory_pct, disk_pct)

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=host_name.lower(),
                asset_type="OBS_HOST",
                environment="PRD",
                criticality="ALTA",
                business_service="OBSERVABILITY",
                ip_address=None,
                operating_system="UNKNOWN",
                cpu_cores=0,
                memory_gb=0,
                disk_gb=0,
                network_mbps=0,
                cluster_name=None,
                namespace=None,
                source="KIBANA",
                provider="ELASTIC",
                external_id=host_name,
                labels_json=json.dumps({"origin": "metrics-hosts"}, ensure_ascii=False),
                is_active=True,
            ),
        )

        host_metrics = [
            ("elastic_host_cpu_usage_percent", cpu_pct, "percent"),
            ("elastic_host_memory_used_percent", memory_pct, "percent"),
            ("elastic_host_disk_used_percent", disk_pct, "percent"),
        ]

        for metric_type, metric_value, metric_unit in host_metrics:
            ingest_metric(
                db,
                MetricCreate(
                    asset_id=asset.id,
                    metric_type=metric_type,
                    metric_value=float(metric_value or 0),
                    metric_unit=metric_unit,
                    collected_at=collected_at,
                    source="KIBANA",
                ),
            )
            update_baseline(db, asset.id, metric_type)
            metrics_written += 1

        top_hosts.append(
            {
                "host": host_name,
                "cpu_usage_percent": cpu_pct,
                "memory_used_percent": memory_pct,
                "disk_used_percent": disk_pct,
                "status": status_level,
            }
        )

        hosts_collected += 1

    for bucket in pod_buckets:
        pod_name = bucket.get("key")
        if not pod_name:
            continue

        cpu_pct = _normalize_pct(bucket.get("cpu_avg", {}).get("value"))
        namespace_buckets = bucket.get("namespace", {}).get("buckets", [])
        namespace = namespace_buckets[0]["key"] if namespace_buckets else None

        status_level = _status_from_usage(cpu_pct, 0.0, 0.0)

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=f"pod-{pod_name}".replace(" ", "-").lower(),
                asset_type="K8S_POD",
                environment="PRD",
                criticality="ALTA",
                business_service="KUBERNETES",
                ip_address=None,
                operating_system="UNKNOWN",
                cpu_cores=0,
                memory_gb=0,
                disk_gb=0,
                network_mbps=0,
                cluster_name=None,
                namespace=namespace,
                source="KIBANA",
                provider="ELASTIC",
                external_id=pod_name,
                labels_json=json.dumps({"origin": "metrics-kubernetes-pods"}, ensure_ascii=False),
                is_active=True,
            ),
        )

        pod_metrics = [
            ("elastic_k8s_pod_cpu_usage_percent", cpu_pct, "percent"),
        ]

        for metric_type, metric_value, metric_unit in pod_metrics:
            ingest_metric(
                db,
                MetricCreate(
                    asset_id=asset.id,
                    metric_type=metric_type,
                    metric_value=float(metric_value or 0),
                    metric_unit=metric_unit,
                    collected_at=collected_at,
                    source="KIBANA",
                ),
            )
            update_baseline(db, asset.id, metric_type)
            metrics_written += 1

        top_pods.append(
            {
                "pod": pod_name,
                "namespace": namespace,
                "cpu_usage_percent": cpu_pct,
                "status": status_level,
            }
        )

        pods_collected += 1

    for bucket in docker_buckets:
        container_name = bucket.get("key")
        if not container_name:
            continue

        cpu_pct = _normalize_pct(bucket.get("cpu_avg", {}).get("value"))
        status_level = _status_from_usage(cpu_pct, 0.0, 0.0)

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=f"ctr-{container_name}".replace(" ", "-").lower(),
                asset_type="CONTAINER",
                environment="PRD",
                criticality="ALTA",
                business_service="CONTAINER",
                ip_address=None,
                operating_system="UNKNOWN",
                cpu_cores=0,
                memory_gb=0,
                disk_gb=0,
                network_mbps=0,
                cluster_name=None,
                namespace=None,
                source="KIBANA",
                provider="ELASTIC",
                external_id=container_name,
                labels_json=json.dumps({"origin": "metrics-docker"}, ensure_ascii=False),
                is_active=True,
            ),
        )

        container_metrics = [
            ("elastic_container_cpu_usage_percent", cpu_pct, "percent"),
        ]

        for metric_type, metric_value, metric_unit in container_metrics:
            ingest_metric(
                db,
                MetricCreate(
                    asset_id=asset.id,
                    metric_type=metric_type,
                    metric_value=float(metric_value or 0),
                    metric_unit=metric_unit,
                    collected_at=collected_at,
                    source="KIBANA",
                ),
            )
            update_baseline(db, asset.id, metric_type)
            metrics_written += 1

        top_containers.append(
            {
                "container": container_name,
                "cpu_usage_percent": cpu_pct,
                "status": status_level,
            }
        )

        containers_collected += 1

    summary_asset, _ = upsert_asset(
        db,
        AssetCreate(
            hostname="kibana-observability-platform",
            asset_type="OBS_PLATFORM",
            environment="PRD",
            criticality="ALTA",
            business_service="OBSERVABILITY",
            ip_address=None,
            operating_system="UNKNOWN",
            cpu_cores=0,
            memory_gb=0,
            disk_gb=0,
            network_mbps=0,
            cluster_name=None,
            namespace=None,
            source="KIBANA",
            provider="KIBANA",
            external_id="kibana-observability-platform",
            labels_json=json.dumps(
                {
                    "kibana_name": status.get("name"),
                    "kibana_version": (status.get("version") or {}).get("number"),
                    "overall_status": ((status.get("status") or {}).get("overall") or {}).get("level"),
                    "data_views_total": len(views),
                },
                ensure_ascii=False,
            ),
            is_active=True,
        ),
    )

    summary_metrics = [
        ("kibana_platform_data_views_total", len(views), "count"),
        ("kibana_platform_hosts_collected", hosts_collected, "count"),
        ("kibana_platform_pods_collected", pods_collected, "count"),
        ("kibana_platform_containers_collected", containers_collected, "count"),
        ("kibana_platform_hosts_high_cpu", hosts_high_cpu, "count"),
        ("kibana_platform_hosts_high_memory", hosts_high_memory, "count"),
        ("kibana_platform_hosts_low_disk", hosts_low_disk, "count"),
    ]

    for metric_type, metric_value, metric_unit in summary_metrics:
        ingest_metric(
            db,
            MetricCreate(
                asset_id=summary_asset.id,
                metric_type=metric_type,
                metric_value=float(metric_value or 0),
                metric_unit=metric_unit,
                collected_at=collected_at,
                source="KIBANA",
            ),
        )
        update_baseline(db, summary_asset.id, metric_type)
        metrics_written += 1

    capacity_status = "ok"
    if hosts_high_cpu > 0 or hosts_high_memory > 0 or hosts_low_disk > 0:
        capacity_status = "warning"
    if any(item["status"] == "critical" for item in top_hosts):
        capacity_status = "critical"

    top_hosts = sorted(
        top_hosts,
        key=lambda x: (
            0 if x["status"] == "critical" else 1 if x["status"] == "warning" else 2,
            -x["cpu_usage_percent"],
            -x["memory_used_percent"],
            -x["disk_used_percent"],
        ),
    )[:5]

    top_pods = sorted(
        top_pods,
        key=lambda x: (
            0 if x["status"] == "critical" else 1 if x["status"] == "warning" else 2,
            -x["cpu_usage_percent"],
        ),
    )[:5]

    top_containers = sorted(
        top_containers,
        key=lambda x: (
            0 if x["status"] == "critical" else 1 if x["status"] == "warning" else 2,
            -x["cpu_usage_percent"],
        ),
    )[:5]

    limitations = []

    if not host_buckets:
        limitations.append("Nenhuma métrica de host foi encontrada em metrics-*.")

    if not pod_buckets:
        limitations.append("Nenhuma métrica de pod foi encontrada em metrics-*.")

    if not docker_buckets:
        limitations.append("Nenhuma métrica de container foi encontrada em metrics-*.")

    if not host_buckets and not pod_buckets and not docker_buckets:
        limitations.append(
            "O Kibana está acessível, mas as métricas úteis de capacity dependem dos índices e campos realmente enviados ao Elasticsearch."
        )

    return {
        "status": "OK",
        "integration": "KIBANA",
        "kibana_name": status.get("name"),
        "kibana_version": (status.get("version") or {}).get("number"),
        "overall_status": ((status.get("status") or {}).get("overall") or {}).get("level"),
        "summary": {
            "capacity_status": capacity_status,
            "data_views_total": len(views),
            "hosts_collected": hosts_collected,
            "pods_collected": pods_collected,
            "containers_collected": containers_collected,
            "avg_host_cpu_percent": _avg(host_cpu_values),
            "avg_host_memory_percent": _avg(host_memory_values),
            "avg_host_disk_percent": _avg(host_disk_values),
            "hosts_high_cpu": hosts_high_cpu,
            "hosts_high_memory": hosts_high_memory,
            "hosts_low_disk": hosts_low_disk,
        },
        "top_hosts": top_hosts,
        "top_pods": top_pods,
        "top_containers": top_containers,
        "data_views": [
            {
                "id": item.get("id"),
                "name": item.get("name") or item.get("title"),
                "title": item.get("title"),
            }
            for item in views
        ],
        "metrics_written": metrics_written,
        "limitations": limitations,
    }