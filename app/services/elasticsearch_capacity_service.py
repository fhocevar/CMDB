from datetime import datetime
import json

from sqlalchemy.orm import Session

from app.integrations.elasticsearch_client import ElasticsearchClient
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def _to_percent(value) -> float:
    if value is None:
        return 0.0

    value = float(value)

    if value <= 1:
        return round(value * 100, 2)

    return round(value, 2)


def collect_from_elasticsearch(db: Session) -> dict:
    try:
        client = ElasticsearchClient()
        hosts_data = client.search_metrics_hosts()
        pods_data = client.search_metrics_kubernetes_pods()
        docker_data = client.search_metrics_docker()
    except Exception as exc:
        return {
            "status": "ERROR",
            "integration": "ELASTICSEARCH",
            "message": str(exc),
        }

    assets_collected = 0
    metrics_written = 0

    host_buckets = hosts_data.get("aggregations", {}).get("by_host", {}).get("buckets", [])
    for bucket in host_buckets:
        host_name = bucket.get("key")

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=f"elastic-host-{host_name}",
                asset_type="ELASTIC_HOST",
                environment="PRD",
                criticality="ALTA",
                business_service="ELASTIC",
                ip_address=None,
                operating_system="UNKNOWN",
                cpu_cores=1,
                memory_gb=0,
                disk_gb=0,
                network_mbps=0,
                cluster_name=None,
                namespace=None,
                source="ELASTICSEARCH",
                provider="ELASTIC",
                external_id=host_name,
                labels_json=json.dumps(bucket, ensure_ascii=False),
                is_active=True,
            ),
        )

        metrics = [
            ("elastic_host_cpu_percent", _to_percent(bucket.get("cpu_avg", {}).get("value")), "percent"),
            ("elastic_host_memory_percent", _to_percent(bucket.get("memory_avg", {}).get("value")), "percent"),
            ("elastic_host_disk_percent", _to_percent(bucket.get("disk_avg", {}).get("value")), "percent"),
        ]

        for metric_type, metric_value, metric_unit in metrics:
            ingest_metric(
                db,
                MetricCreate(
                    asset_id=asset.id,
                    metric_type=metric_type,
                    metric_value=metric_value,
                    metric_unit=metric_unit,
                    collected_at=datetime.utcnow(),
                    source="ELASTICSEARCH",
                ),
            )
            update_baseline(db, asset.id, metric_type)
            metrics_written += 1

        assets_collected += 1

    pod_buckets = pods_data.get("aggregations", {}).get("by_pod", {}).get("buckets", [])
    for bucket in pod_buckets:
        pod_name = bucket.get("key")
        namespace_bucket = bucket.get("namespace", {}).get("buckets", [])
        namespace = namespace_bucket[0]["key"] if namespace_bucket else None

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=f"elastic-pod-{pod_name}",
                asset_type="ELASTIC_K8S_POD",
                environment="PRD",
                criticality="ALTA",
                business_service="ELASTIC",
                ip_address=None,
                operating_system="CONTAINER",
                cpu_cores=1,
                memory_gb=0,
                disk_gb=0,
                network_mbps=0,
                cluster_name=None,
                namespace=namespace,
                source="ELASTICSEARCH",
                provider="ELASTIC",
                external_id=pod_name,
                labels_json=json.dumps(bucket, ensure_ascii=False),
                is_active=True,
            ),
        )

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="elastic_k8s_pod_cpu_percent",
                metric_value=_to_percent(bucket.get("cpu_avg", {}).get("value")),
                metric_unit="percent",
                collected_at=datetime.utcnow(),
                source="ELASTICSEARCH",
            ),
        )
        update_baseline(db, asset.id, "elastic_k8s_pod_cpu_percent")
        metrics_written += 1
        assets_collected += 1

    docker_buckets = docker_data.get("aggregations", {}).get("by_container", {}).get("buckets", [])
    for bucket in docker_buckets:
        container_name = bucket.get("key")

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=f"elastic-docker-{container_name}",
                asset_type="ELASTIC_DOCKER_CONTAINER",
                environment="PRD",
                criticality="ALTA",
                business_service="ELASTIC",
                ip_address=None,
                operating_system="CONTAINER",
                cpu_cores=1,
                memory_gb=0,
                disk_gb=0,
                network_mbps=0,
                cluster_name=None,
                namespace=None,
                source="ELASTICSEARCH",
                provider="ELASTIC",
                external_id=container_name,
                labels_json=json.dumps(bucket, ensure_ascii=False),
                is_active=True,
            ),
        )

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="elastic_docker_cpu_percent",
                metric_value=_to_percent(bucket.get("cpu_avg", {}).get("value")),
                metric_unit="percent",
                collected_at=datetime.utcnow(),
                source="ELASTICSEARCH",
            ),
        )
        update_baseline(db, asset.id, "elastic_docker_cpu_percent")
        metrics_written += 1
        assets_collected += 1

    return {
        "status": "OK",
        "integration": "ELASTICSEARCH",
        "assets_collected": assets_collected,
        "metrics_written": metrics_written,
    }