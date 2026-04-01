from fastapi import FastAPI
from sqlalchemy.orm import Session
from app.api.routes import jenkins
from app.api.routes import jenkins_jobs
from app.api.routes.agents import router as agents_router
from app.api.routes.assets import router as assets_router
from app.api.routes.auth import router as auth_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.discovery import router as discovery_router
from app.api.routes.exports import router as exports_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.thresholds import router as thresholds_router
from app.api.routes import applications
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.scheduler import start_scheduler
from app.core.security import hash_password
from app.api.routes import jenkins_jobs
# IMPORTS DOS MODELS QUE PRECISAM ESTAR REGISTRADOS NO METADATA
from app.models.app_capacity_snapshot import AppCapacitySnapshot
from app.models.threshold_policy import ThresholdPolicy
from app.models.user import User

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

Base.metadata.create_all(bind=engine)


def seed_admin_and_thresholds():
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin").first()
        if not user:
            db.add(
                User(
                    username="admin",
                    full_name="Administrador",
                    email="admin@empresa.com",
                    password_hash=hash_password("admin123"),
                    is_admin=True,
                    is_active=True,
                )
            )
            db.commit()

        defaults = [
            ("DEFAULT", "cpu_percent", 70, 85, 95),
            ("DEFAULT", "memory_percent", 75, 90, 97),
            ("DEFAULT", "disk_percent", 80, 90, 95),
            ("DEFAULT", "network_percent", 70, 85, 95),
            ("SERVER", "cpu_percent", 70, 85, 95),
            ("SERVER", "memory_percent", 75, 90, 97),
            ("SERVER", "disk_percent", 80, 90, 95),
            ("SERVER", "network_percent", 70, 85, 95),
            ("DOCKER_CONTAINER", "container_cpu_percent", 70, 85, 95),
            ("DOCKER_CONTAINER", "container_memory_percent", 75, 90, 97),
            ("DOCKER_CONTAINER", "container_network_percent", 70, 85, 95),
            ("K8S_NODE", "cpu_percent", 75, 90, 95),
            ("K8S_POD", "cpu_percent", 75, 90, 95),
            ("ARGOCD_APPLICATION", "argocd_sync_state", 1, 50, 100),
            ("ARGOCD_APPLICATION", "argocd_health_state", 1, 50, 100),
            ("JENKINS_AGENT", "jenkins_executor_usage_percent", 70, 85, 95),
            ("JENKINS_CONTROLLER", "jenkins_executor_usage_percent", 70, 85, 95),
            ("JENKINS_AGENT", "jenkins_offline_state", 1, 50, 100),
            ("JENKINS_CONTROLLER", "jenkins_offline_state", 1, 50, 100),
            ("JENKINS_AGENT", "jenkins_temp_offline_state", 1, 50, 100),
            ("JENKINS_CONTROLLER", "jenkins_temp_offline_state", 1, 50, 100),

            ("ELASTIC_HOST", "elastic_host_cpu_percent", 70, 85, 95),
            ("ELASTIC_HOST", "elastic_host_memory_percent", 75, 90, 97),
            ("ELASTIC_HOST", "elastic_host_disk_percent", 80, 90, 95),
            ("ELASTIC_K8S_POD", "elastic_k8s_pod_cpu_percent", 75, 90, 95),
            ("ELASTIC_DOCKER_CONTAINER", "elastic_docker_cpu_percent", 75, 90, 95),
        ]

        for asset_type, metric_type, warning, critical, saturation in defaults:
            existing = (
                db.query(ThresholdPolicy)
                .filter(ThresholdPolicy.asset_type == asset_type)
                .filter(ThresholdPolicy.metric_type == metric_type)
                .first()
            )
            if not existing:
                db.add(
                    ThresholdPolicy(
                        asset_type=asset_type,
                        metric_type=metric_type,
                        warning_percent=warning,
                        critical_percent=critical,
                        saturation_percent=saturation,
                        trend_window_hours=24,
                        is_active=True,
                    )
                )
        db.commit()
    finally:
        db.close()


seed_admin_and_thresholds()
start_scheduler()
app.include_router(jenkins_jobs.router)
app.include_router(jenkins.router)
app.include_router(jenkins_jobs.router)
app.include_router(auth_router)
app.include_router(assets_router)
app.include_router(metrics_router)
app.include_router(thresholds_router)
app.include_router(dashboard_router)
app.include_router(discovery_router)
app.include_router(agents_router)
app.include_router(integrations_router)
app.include_router(exports_router)
app.include_router(applications.router)


@app.get("/")
def healthcheck():
    return {"message": "ITIL Capacity Management API V2.2 online"}