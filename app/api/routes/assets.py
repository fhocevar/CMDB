from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.asset import Asset
from app.schemas.asset import AssetCreate, AssetResponse
from app.services.asset_service import upsert_asset

router = APIRouter(prefix="/assets", tags=["Assets"])


@router.post("/", response_model=AssetResponse)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    asset, _ = upsert_asset(db, payload)
    return asset


@router.get("/", response_model=list[AssetResponse])
def list_assets(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(Asset).order_by(Asset.hostname).all()
