from datetime import datetime
import json

from sqlalchemy.orm import Session

from app.integrations.elasticsearch_client import ElasticsearchClient
from app.integrations.kibana_client import KibanaClient
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip().replace("%", "")
            if not value:
                return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bytes_to_mb(value) -> float:
    if value is None:
        return 0.0
    return round(float(value) / (1024 * 1024), 2)


def _bytes_to_gb(value) -> float:
    if value is None:
        return 0.0
    return round(float(value) / (1024 * 1024 * 1024), 2)


def _normalize_pct(value) -> float:
    if value is None:
        return 0.0
    value = float(value)
    if value <= 1:
        value *= 100.0
    return round(value, 2)


def _pick_field(field_caps: dict, candidates: list[str]) -> str | None:
    fields = field_caps.get("fields", {})
    for candidate in candidates:
        if candidate in fields:
            return candidate
    return None


def collect_from_kibana(db: Session) -> dict:
    try:
        kibana = KibanaClient()
        es = ElasticsearchClient()

        status = kibana.get_status()
        data_views_payload = kibana.list_data_views()

        metrics_caps = es.field_caps("metrics-*")
        apm_caps = es.field_caps(
            "traces-apm*,apm-*,metrics-apm*,logs-apm*,traces-*.otel-*,metrics-*.otel-*"
        )
    except Exception as exc:
        return {
            "status": "ERROR",
            "integration": "KIBANA",
            "message": str(exc),
        }

    views = data_views_payload.get("data_view", []) or data_views_payload.get("data_views", []) or []
    collected_at = datetime.utcnow()
    metrics_written = 0

    host_field = _pick_field(metrics_caps, ["host.name", "agent.name", "kubernetes.node.name"])
    cpu_field = _pick_field(metrics_caps, ["system.cpu.total.norm.pct", "host.cpu.usage"])
    mem_pct_field = _pick_field(metrics_caps, ["system.memory.actual.used.pct", "system.memory.used.pct"])
    mem_total_field = _pick_field(metrics_caps, ["system.memory.total"])
    mem_used_field = _pick_field(metrics_caps, ["system.memory.actual.used.bytes", "system.memory.used.bytes"])
    disk_pct_field = _pick_field(metrics_caps, ["system.filesystem.used.pct", "host.disk.usage"])
    disk_total_field = _pick_field(metrics_caps, ["system.filesystem.total"])
    disk_used_field = _pick_field(metrics_caps, ["system.filesystem.used.bytes"])

    hosts_collected = 0
    services_collected = 0
    hosts_high_cpu = 0
    hosts_high_memory = 0
    hosts_low_disk = 0
    services_high_error_rate = 0
    services_high_latency = 0

    if host_field:
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": "now-15m",
                                    "lte": "now"
                                }
                            }
                        }
                    ]
                }
            },
            "aggs": {
                "by_host": {
                    "terms": {
                        "field": host_field,
                        "size": 200
                    },
                    "aggs": {}
                }
            }
        }

        bucket_aggs = body["aggs"]["by_host"]["aggs"]

        if cpu_field:
            bucket_aggs["cpu_usage_pct"] = {"avg": {"field": cpu_field}}
        if mem_pct_field:
            bucket_aggs["memory_used_pct"] = {"avg": {"field": mem_pct_field}}
        if mem_total_field:
            bucket_aggs["memory_total"] = {"max": {"field": mem_total_field}}
        if mem_used_field:
            bucket_aggs["memory_used"] = {"max": {"field": mem_used_field}}
        if disk_pct_field:
            bucket_aggs["disk_used_pct"] = {"avg": {"field": disk_pct_field}}
        if disk_total_field:
            bucket_aggs["disk_total"] = {"max": {"field": disk_total_field}}
        if disk_used_field:
            bucket_aggs["disk_used"] = {"max": {"field": disk_used_field}}

        response = es.search("metrics-*", body)
        buckets = response.get("aggregations", {}).get("by_host", {}).get("buckets", [])

        for bucket in buckets:
            host_name = bucket.get("key")
            if not host_name:
                continue

            cpu_usage_pct = _normalize_pct(bucket.get("cpu_usage_pct", {}).get("value"))
            memory_used_pct = _normalize_pct(bucket.get("memory_used_pct", {}).get("value"))
            disk_used_pct = _normalize_pct(bucket.get("disk_used_pct", {}).get("value"))

            memory_total_mb = _bytes_to_mb(bucket.get("memory_total", {}).get("value"))
            memory_used_mb = _bytes_to_mb(bucket.get("memory_used", {}).get("value"))
            disk_total_gb = _bytes_to_gb(bucket.get("disk_total", {}).get("value"))
            disk_used_gb = _bytes_to_gb(bucket.get("disk_used", {}).get("value"))

            if cpu_usage_pct >= 80:
                hosts_high_cpu += 1
            if memory_used_pct >= 85:
                hosts_high_memory += 1
            if disk_used_pct >= 85:
                hosts_low_disk += 1

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
                    memory_gb=round(memory_total_mb / 1024, 2) if memory_total_mb else 0,
                    disk_gb=disk_total_gb,
                    network_mbps=0,
                    cluster_name=None,
                    namespace=None,
                    source="KIBANA",
                    provider="ELASTIC",
                    external_id=host_name,
                    labels_json=json.dumps({"origin": "metrics-*"}, ensure_ascii=False),
                    is_active=True,
                ),
            )

            host_metrics = [
                ("elastic_host_cpu_usage_percent", cpu_usage_pct, "percent"),
                ("elastic_host_memory_used_percent", memory_used_pct, "percent"),
                ("elastic_host_memory_used_mb", memory_used_mb, "mb"),
                ("elastic_host_memory_total_mb", memory_total_mb, "mb"),
                ("elastic_host_disk_used_percent", disk_used_pct, "percent"),
                ("elastic_host_disk_used_gb", disk_used_gb, "gb"),
                ("elastic_host_disk_total_gb", disk_total_gb, "gb"),
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

            hosts_collected += 1

    service_field = _pick_field(apm_caps, ["service.name"])
    env_field = _pick_field(apm_caps, ["service.environment"])
    transaction_field = _pick_field(apm_caps, ["transaction.id", "trace.id"])
    duration_field = _pick_field(apm_caps, ["transaction.duration.us", "event.duration"])
    outcome_field = _pick_field(apm_caps, ["event.outcome"])

    if service_field:
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": "now-15m",
                                    "lte": "now"
                                }
                            }
                        }
                    ]
                }
            },
            "aggs": {
                "by_service": {
                    "terms": {
                        "field": service_field,
                        "size": 200
                    },
                    "aggs": {}
                }
            }
        }

        bucket_aggs = body["aggs"]["by_service"]["aggs"]

        if env_field:
            bucket_aggs["environment"] = {"terms": {"field": env_field, "size": 1}}
        if transaction_field:
            bucket_aggs["total_transactions"] = {"value_count": {"field": transaction_field}}
        if duration_field:
            bucket_aggs["latency_avg"] = {"avg": {"field": duration_field}}
            bucket_aggs["latency_p95"] = {"percentiles": {"field": duration_field, "percents": [95]}}
        if outcome_field:
            bucket_aggs["failed"] = {"filter": {"term": {outcome_field: "failure"}}}

        response = es.search(
            "traces-apm*,apm-*,metrics-apm*,logs-apm*,traces-*.otel-*,metrics-*.otel-*",
            body,
        )
        buckets = response.get("aggregations", {}).get("by_service", {}).get("buckets", [])

        for bucket in buckets:
            service_name = bucket.get("key")
            if not service_name:
                continue

            total_transactions = int(bucket.get("total_transactions", {}).get("value", 0) or 0)
            failed_transactions = int(bucket.get("failed", {}).get("doc_count", 0) or 0)

            error_rate_pct = round((failed_transactions / total_transactions) * 100.0, 2) if total_transactions else 0.0

            latency_avg_raw = bucket.get("latency_avg", {}).get("value")
            latency_p95_raw = bucket.get("latency_p95", {}).get("values", {}).get("95.0")

            latency_avg_ms = round(latency_avg_raw / 1000.0, 2) if latency_avg_raw is not None else 0.0
            latency_p95_ms = round(latency_p95_raw / 1000.0, 2) if latency_p95_raw is not None else 0.0
            throughput_tpm = round(total_transactions / 15.0, 2)

            if error_rate_pct >= 3:
                services_high_error_rate += 1
            if latency_p95_ms >= 2000:
                services_high_latency += 1

            env_buckets = bucket.get("environment", {}).get("buckets", [])
            environment = env_buckets[0]["key"] if env_buckets else "PRD"

            asset, _ = upsert_asset(
                db,
                AssetCreate(
                    hostname=f"svc-{service_name}".replace(" ", "-").lower(),
                    asset_type="OBS_SERVICE",
                    environment=environment,
                    criticality="ALTA",
                    business_service=service_name,
                    ip_address=None,
                    operating_system="UNKNOWN",
                    cpu_cores=0,
                    memory_gb=0,
                    disk_gb=0,
                    network_mbps=0,
                    cluster_name=None,
                    namespace=None,
                    source="KIBANA",
                    provider="ELASTIC_APM",
                    external_id=service_name,
                    labels_json=json.dumps({"origin": "apm"}, ensure_ascii=False),
                    is_active=True,
                ),
            )

            service_metrics = [
                ("elastic_service_throughput_tpm", throughput_tpm, "tpm"),
                ("elastic_service_latency_avg_ms", latency_avg_ms, "ms"),
                ("elastic_service_latency_p95_ms", latency_p95_ms, "ms"),
                ("elastic_service_error_rate_percent", error_rate_pct, "percent"),
                ("elastic_service_failed_transactions", failed_transactions, "count"),
            ]

            for metric_type, metric_value, metric_unit in service_metrics:
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

            services_collected += 1

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
        ("kibana_platform_services_collected", services_collected, "count"),
        ("kibana_platform_hosts_high_cpu", hosts_high_cpu, "count"),
        ("kibana_platform_hosts_high_memory", hosts_high_memory, "count"),
        ("kibana_platform_hosts_low_disk", hosts_low_disk, "count"),
        ("kibana_platform_services_high_error_rate", services_high_error_rate, "count"),
        ("kibana_platform_services_high_latency", services_high_latency, "count"),
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

    return {
        "status": "OK",
        "integration": "KIBANA",
        "kibana_name": status.get("name"),
        "kibana_version": (status.get("version") or {}).get("number"),
        "overall_status": ((status.get("status") or {}).get("overall") or {}).get("level"),
        "data_views_total": len(views),
        "hosts_collected": hosts_collected,
        "services_collected": services_collected,
        "metrics_written": metrics_written,
    }