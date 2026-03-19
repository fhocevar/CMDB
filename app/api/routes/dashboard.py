from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.schemas.dashboard import DashboardSummary
from app.services.capacity_service import build_dashboard

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/capacity", response_model=DashboardSummary)
def get_dashboard(
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return build_dashboard(db, hours=hours)
