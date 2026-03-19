from datetime import datetime

from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.schemas.asset import AssetCreate


def upsert_asset(db: Session, payload: AssetCreate) -> tuple[Asset, bool]:
    existing = db.query(Asset).filter(Asset.hostname == payload.hostname).first()

    if existing:
        data = payload.model_dump()
        for key, value in data.items():
            setattr(existing, key, value)
        existing.last_seen_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing, False

    asset = Asset(**payload.model_dump(), last_seen_at=datetime.utcnow())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset, True
