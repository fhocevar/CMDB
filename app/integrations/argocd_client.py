from datetime import datetime

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


class ArgoCDClient:
    def __init__(self):
        self.base_url = settings.ARGOCD_URL.rstrip("/") if settings.ARGOCD_URL else ""
        self.session = requests.Session()
        self.token = None

        if not settings.ARGOCD_VERIFY_TLS:
            requests.packages.urllib3.disable_warnings()

    def login(self) -> None:
        if not self.base_url:
            raise ValueError("ARGOCD_URL não configurado")

        url = f"{self.base_url}/api/v1/session"
        payload = {
            "username": settings.ARGOCD_USERNAME,
            "password": settings.ARGOCD_PASSWORD,
        }

        response = self.session.post(
            url,
            json=payload,
            timeout=30,
            verify=settings.ARGOCD_VERIFY_TLS,
        )
        response.raise_for_status()

        self.token = response.json().get("token")
        if not self.token:
            raise ValueError("Token do Argo CD não retornado")

        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
        )

    def get_application(self, app_name: str) -> dict:
        url = f"{self.base_url}/api/v1/applications/{app_name}"
        response = self.session.get(
            url,
            timeout=30,
            verify=settings.ARGOCD_VERIFY_TLS,
        )
        response.raise_for_status()
        return response.json()

    def list_applications(self) -> list[dict]:
        url = f"{self.base_url}/api/v1/applications"
        response = self.session.get(
            url,
            timeout=30,
            verify=settings.ARGOCD_VERIFY_TLS,
        )
        response.raise_for_status()
        return response.json().get("items", [])


def _status_to_metric_value_ok_bad(value: str, ok_value: str) -> float:
    if not value:
        return 100.0
    return 0.0 if value.lower() == ok_value.lower() else 100.0


def collect_from_argocd(db: Session) -> None:
    if not settings.ARGOCD_ENABLED:
        return

    if not settings.ARGOCD_URL or not settings.ARGOCD_USERNAME or not settings.ARGOCD_PASSWORD:
        return

    client = ArgoCDClient()
    client.login()
    apps = client.list_applications()

    critical_apps = set(settings.critical_apps) if hasattr(settings, "critical_apps") else set()

    for app in apps:
        metadata = app.get("metadata", {})
        spec = app.get("spec", {})
        status = app.get("status", {})

        app_name = metadata.get("name")
        if not app_name:
            continue

        if critical_apps and app_name not in critical_apps:
            continue

        project = spec.get("project", "default")
        destination = spec.get("destination", {}) or {}
        source = spec.get("source", {}) or {}
        sync = status.get("sync", {}) or {}
        health = status.get("health", {}) or {}

        namespace = destination.get("namespace")
        cluster = destination.get("server")
        sync_status = sync.get("status", "Unknown")
        health_status = health.get("status", "Unknown")

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
                labels_json=str(
                    {
                        "repo_url": source.get("repoURL"),
                        "target_revision": source.get("targetRevision"),
                        "path": source.get("path"),
                        "project": project,
                    }
                ),
                parent_asset_id=None,
                is_active=True,
            ),
        )

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="argocd_sync_state",
                metric_value=_status_to_metric_value_ok_bad(sync_status, "Synced"),
                metric_unit="percent",
                collected_at=datetime.utcnow(),
                source="ARGOCD",
            ),
        )
        update_baseline(db, asset.id, "argocd_sync_state")

        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type="argocd_health_state",
                metric_value=_status_to_metric_value_ok_bad(health_status, "Healthy"),
                metric_unit="percent",
                collected_at=datetime.utcnow(),
                source="ARGOCD",
            ),
        )
        update_baseline(db, asset.id, "argocd_health_state")