from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.services.jenkins_jobs_capacity_service import JenkinsJobsCapacityService

router = APIRouter(prefix="/jenkins/jobs", tags=["Jenkins Jobs"])


@router.post("/collect")
def collect_jenkins_jobs(
    max_jobs: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    #user=Depends(get_current_user),
):
    service = JenkinsJobsCapacityService(db)
    return service.collect_and_persist_jobs_snapshot(max_jobs=max_jobs)


@router.get("/history")
def get_jenkins_jobs_history(
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    #user=Depends(get_current_user),
):
    service = JenkinsJobsCapacityService(db)
    return service.get_jobs_history(limit=limit)


@router.get("/summary")
def get_jenkins_jobs_summary(
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    #user=Depends(get_current_user),
):
    service = JenkinsJobsCapacityService(db)
    return service.get_jobs_summary(limit=limit)