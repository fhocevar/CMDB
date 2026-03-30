from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.services.application_service import ApplicationService
from app.services.jenkins_snapshot_service import build_jenkins_capacity_snapshot

router = APIRouter(prefix="/applications", tags=["Applications"])


@router.post("/capacity/collect")
def collect_capacity(db: Session = Depends(get_db)):
    service = ApplicationService(db)
    return service.collect_and_persist()


@router.get("/capacity")
def list_capacity_live(db: Session = Depends(get_db)):
    service = ApplicationService(db)
    return service.list_capacity_live()


@router.get("/capacity/dashboard")
def get_capacity_dashboard(db: Session = Depends(get_db)):
    service = ApplicationService(db)
    return service.get_grafana_dashboard()


@router.get("/capacity/history")
def get_capacity_history(days: int = 30, db: Session = Depends(get_db)):
    service = ApplicationService(db)
    return service.get_capacity_history(days=days)


@router.get("/capacity/dashboard/html", response_class=HTMLResponse)
def get_capacity_dashboard_html(db: Session = Depends(get_db)):
    service = ApplicationService(db)
    return service.render_dashboard_html()


@router.get("/capacity/{app_name}")
def get_capacity(app_name: str, db: Session = Depends(get_db)):
    service = ApplicationService(db)
    return service.get_application_capacity(app_name)


@router.get("/capacity/jenkins/snapshot")
def get_jenkins_capacity_snapshot(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return build_jenkins_capacity_snapshot(db)