import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.services.capacity_service import build_dashboard
from app.services.export_service import dashboard_to_csv_bytes

router = APIRouter(prefix="/exports", tags=["Exports"])


@router.get("/capacity.csv")
def export_dashboard_csv(
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    dashboard = build_dashboard(db, hours=hours)
    content = dashboard_to_csv_bytes(dashboard)

    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=itil_capacity_v2_2_{hours}h.csv"},
    )
