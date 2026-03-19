from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.schemas.metric import MetricCreate, MetricResponse
from app.services.metric_service import ingest_metric, update_baseline

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.post("/", response_model=MetricResponse)
def create_metric(payload: MetricCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    metric = ingest_metric(db, payload)
    update_baseline(db, payload.asset_id, payload.metric_type)
    return metric
