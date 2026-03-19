from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.discovery.runner import run_discovery_cycle
from app.schemas.discovery import DiscoveryRunResponse

router = APIRouter(prefix="/discovery", tags=["Discovery"])


@router.post("/run", response_model=DiscoveryRunResponse)
def run_discovery(db: Session = Depends(get_db), user=Depends(get_current_user)):
    result = run_discovery_cycle(db)
    return DiscoveryRunResponse(
        source_name="DISCOVERY_CYCLE",
        status=result["status"],
        assets_found=result.get("assets_found", 0),
        assets_updated=result.get("assets_updated", 0),
        message=result.get("message", "Discovery executado"),
    )
