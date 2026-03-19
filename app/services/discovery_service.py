from datetime import datetime

from sqlalchemy.orm import Session

from app.models.discovery_job import DiscoveryJob
from app.schemas.asset import AssetCreate
from app.services.asset_service import upsert_asset


def create_discovery_job(db: Session, source_name: str) -> DiscoveryJob:
    job = DiscoveryJob(
        source_name=source_name,
        status="RUNNING",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def finalize_discovery_job(
    db: Session,
    job: DiscoveryJob,
    status: str,
    assets_found: int,
    assets_updated: int,
    error_message: str | None = None,
) -> None:
    job.status = status
    job.assets_found = assets_found
    job.assets_updated = assets_updated
    job.error_message = error_message
    job.finished_at = datetime.utcnow()
    db.commit()


def persist_discovered_assets(db: Session, assets: list[AssetCreate]) -> tuple[int, int]:
    created_count = 0
    updated_count = 0

    for item in assets:
        _, created = upsert_asset(db, item)
        if created:
            created_count += 1
        else:
            updated_count += 1

    return created_count, updated_count
