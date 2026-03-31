from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.services.jenkins_dashboard_service import JenkinsDashboardService

router = APIRouter(prefix="/jenkins", tags=["Jenkins"])


@router.post("/capacity/collect")
def collect_jenkins_capacity(
    db: Session = Depends(get_db),
    #user=Depends(get_current_user),
):
    service = JenkinsDashboardService(db)
    return service.collect_and_persist_snapshot()


@router.get("/capacity/dashboard")
def get_jenkins_dashboard(
    db: Session = Depends(get_db),
    #user=Depends(get_current_user),
):
    service = JenkinsDashboardService(db)
    return service.get_dashboard_data()


@router.get("/capacity/history")
def get_jenkins_history(
    limit: int = Query(default=30, ge=1, le=500),
    db: Session = Depends(get_db),
    #user=Depends(get_current_user),
):
    service = JenkinsDashboardService(db)
    return service.get_history(limit)


@router.get("/capacity/forecast")
def get_jenkins_forecast(
    steps: int = Query(default=6, ge=1, le=24),
    db: Session = Depends(get_db),
    #user=Depends(get_current_user),
):
    service = JenkinsDashboardService(db)
    return service.get_forecast(steps)


@router.get("/capacity/forecast/agents")
def get_jenkins_agents_forecast(
    steps: int = Query(default=6, ge=1, le=24),
    db: Session = Depends(get_db),
    #user=Depends(get_current_user),
):
    service = JenkinsDashboardService(db)
    return service.get_agents_forecast(steps)


@router.get("/capacity/dashboard/html", response_class=HTMLResponse)
def get_jenkins_dashboard_html(
    db: Session = Depends(get_db),
    #user=Depends(get_current_user), (utilização de token autenticação)
):
    service = JenkinsDashboardService(db)
    return service.render_dashboard_html()