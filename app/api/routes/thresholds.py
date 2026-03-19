from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.threshold_policy import ThresholdPolicy
from app.schemas.threshold import ThresholdPolicyCreate, ThresholdPolicyResponse

router = APIRouter(prefix="/thresholds", tags=["Thresholds"])


@router.post("/", response_model=ThresholdPolicyResponse)
def create_threshold(payload: ThresholdPolicyCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    obj = ThresholdPolicy(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[ThresholdPolicyResponse])
def list_thresholds(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(ThresholdPolicy).order_by(ThresholdPolicy.asset_type, ThresholdPolicy.metric_type).all()
