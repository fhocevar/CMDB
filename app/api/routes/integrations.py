from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.integrations.argocd_client import collect_from_argocd
from app.integrations.kubernetes_client import collect_from_kubernetes
from app.integrations.prometheus_client import collect_from_prometheus
from app.integrations.vmware_client import collect_from_vmware
from app.integrations.zabbix_client import collect_from_zabbix

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.post("/prometheus/run")
def run_prometheus(db: Session = Depends(get_db), user=Depends(get_current_user)):
    collect_from_prometheus(db)
    return {"status": "OK", "integration": "PROMETHEUS"}


@router.post("/kubernetes/run")
def run_kubernetes(db: Session = Depends(get_db), user=Depends(get_current_user)):
    collect_from_kubernetes(db)
    return {"status": "OK", "integration": "KUBERNETES"}


@router.post("/argocd/run")
def run_argocd(db: Session = Depends(get_db), user=Depends(get_current_user)):
    collect_from_argocd(db)
    return {"status": "OK", "integration": "ARGOCD"}


@router.post("/zabbix/run")
def run_zabbix(db: Session = Depends(get_db), user=Depends(get_current_user)):
    collect_from_zabbix(db)
    return {"status": "OK", "integration": "ZABBIX"}


@router.post("/vmware/run")
def run_vmware(db: Session = Depends(get_db), user=Depends(get_current_user)):
    collect_from_vmware(db)
    return {"status": "OK", "integration": "VMWARE"}
