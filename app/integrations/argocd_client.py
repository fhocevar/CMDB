import re
from datetime import datetime

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline

ARGCD_APP_INFO_RE = re.compile(r'^argocd_app_info\{(?P<labels>.+?)\}\s+(?P<value>[0-9.]+)$')


def _parse_labels(raw: str) -> dict[str, str]:
    labels = {}
    parts = re.findall(r'(\w+?)="(.*?)"', raw)
    for key, value in parts:
        labels[key] = value
    return labels


def _sync_status_to_value(sync_status: str) -> float:
    return 0.0 if sync_status.lower() == "synced" else 100.0


def _health_status_to_value(health_status: str) -> float:
    return 0.0 if health_status.lower() == "healthy" else 100.0


def collect_from_argocd(db: Session) -> None:
    if not settings.ARGOCD_METRICS_URL:
        return

    response = requests.get(settings.ARGOCD_METRICS_URL, timeout=20)
    response.raise_for_status()

    for line in response.text.splitlines():
        line = line.strip()
        if not line.startswith("argocd_app_info{"):
            continue

        match = ARGCD_APP_INFO_RE.match(line)
        if not match:
            continue

        labels = _parse_labels(match.group("labels"))

        app_name = labels.get("name")
        project = labels.get("project", "default")
        namespace = labels.get("dest_namespace", "")
        cluster = labels.get("dest_server", "")
        sync_status = labels.get("sync_status", "Unknown")
        health_status = labels.get("health_status", "Unknown")

        if not app_name:
            continue

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=f"argocd-app-{app_name}",
                asset_type="ARGOCD_APPLICATION",
                environment="PRD",
                criticality="ALTA",
                business_service=project.upper(),
                ip_address=None,
                operating_system="KUBERNETES",
                cpu_cores=0,
                memory_gb=0,
                disk_gb=0,
                network_mbps=0,
                cluster_name=cluster,
                namespace=namespace,
                source="ARGOCD",
                provider="ARGOCD",
                external_id=app_name,
                labels_json=str(labels),
            ),
        )

        now = datetime.utcnow()

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="argocd_sync_state",
                metric_value=_sync_status_to_value(sync_status),
                metric_unit="percent",
                collected_at=now,
                source="ARGOCD",
            ),
        )
        update_baseline(db, asset.id, "argocd_sync_state")

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="argocd_health_state",
                metric_value=_health_status_to_value(health_status),
                metric_unit="percent",
                collected_at=now,
                source="ARGOCD",
            ),
        )
        update_baseline(db, asset.id, "argocd_health_state")
