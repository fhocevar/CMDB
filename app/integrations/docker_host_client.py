from datetime import datetime

from sqlalchemy.orm import Session

from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def ingest_docker_container_metrics(
    db: Session,
    host_asset_id: int,
    hostname: str,
    container_id: str,
    container_name: str,
    cpu_percent: float,
    memory_percent: float,
    network_percent: float,
    environment: str = "PRD",
    business_service: str = "DOCKER",
) -> None:
    asset, _ = upsert_asset(
        db,
        AssetCreate(
            hostname=f"{hostname}-docker-{container_name}",
            asset_type="DOCKER_CONTAINER",
            environment=environment,
            criticality="ALTA",
            business_service=business_service,
            operating_system="CONTAINER",
            cpu_cores=1,
            memory_gb=1,
            disk_gb=1,
            network_mbps=1000,
            source="AGENT_DOCKER",
            provider="DOCKER",
            external_id=container_id,
            parent_asset_id=host_asset_id,
        ),
    )

    now = datetime.utcnow()

    for metric_type, metric_value in [
        ("container_cpu_percent", cpu_percent),
        ("container_memory_percent", memory_percent),
        ("container_network_percent", network_percent),
    ]:
        ingest_metric(
            db,
            MetricCreate(
                asset_id=asset.id,
                metric_type=metric_type,
                metric_value=round(metric_value, 2),
                metric_unit="percent",
                collected_at=now,
                source="AGENT_DOCKER",
            ),
        )
        update_baseline(db, asset.id, metric_type)
