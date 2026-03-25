from fastapi import APIRouter
from app.services.application_service import ApplicationService

router = APIRouter(prefix="/applications", tags=["Applications"])


@router.get("/capacity")
def list_capacity():
    service = ApplicationService()
    return service.list_critical_apps()


@router.get("/capacity/summary")
def get_capacity_summary():
    service = ApplicationService()
    return service.summarize_applications()


@router.get("/capacity/{app_name}")
def get_capacity(app_name: str):
    service = ApplicationService()
    return service.get_application_capacity(app_name)