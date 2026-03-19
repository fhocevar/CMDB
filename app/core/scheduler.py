from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.core.database import SessionLocal
from app.discovery.runner import run_discovery_cycle
from app.integrations.argocd_client import collect_from_argocd
from app.integrations.kubernetes_client import collect_from_kubernetes
from app.integrations.prometheus_client import collect_from_prometheus
from app.integrations.vmware_client import collect_from_vmware
from app.integrations.zabbix_client import collect_from_zabbix

scheduler = BackgroundScheduler()


def scheduled_discovery():
    db = SessionLocal()
    try:
        run_discovery_cycle(db)
    finally:
        db.close()


def scheduled_integrations():
    db = SessionLocal()
    try:
        if settings.PROMETHEUS_ENABLED:
            collect_from_prometheus(db)
        if settings.KUBERNETES_ENABLED:
            collect_from_kubernetes(db)
        if settings.ARGOCD_ENABLED:
            collect_from_argocd(db)
        if settings.ZABBIX_ENABLED:
            collect_from_zabbix(db)
        if settings.VMWARE_ENABLED:
            collect_from_vmware(db)
    finally:
        db.close()


def start_scheduler():
    scheduler.add_job(scheduled_discovery, "interval", minutes=30, id="discovery_cycle", replace_existing=True)
    scheduler.add_job(scheduled_integrations, "interval", minutes=5, id="integration_cycle", replace_existing=True)
    scheduler.start()
