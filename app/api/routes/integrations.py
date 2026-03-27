from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.integrations.argocd_client import collect_from_argocd
from app.integrations.kubernetes_client import collect_from_kubernetes
from app.integrations.prometheus_client import collect_from_prometheus
from app.integrations.vmware_client import collect_from_vmware
from app.integrations.zabbix_client import collect_from_zabbix
from app.services.jenkins_capacity_service import collect_from_jenkins
from app.services.elasticsearch_capacity_service import collect_from_elasticsearch
from app.services.kibana_discovery_service import discover_kibana
from app.services.kibana_capacity_service import collect_from_kibana


router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.post("/prometheus/run")
def run_prometheus(db: Session = Depends(get_db), user=Depends(get_current_user)):
    collect_from_prometheus(db)
    return {"status": "OK", "integration": "PROMETHEUS"}


@router.post("/kubernetes/run")
def run_kubernetes(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return collect_from_kubernetes(db)


@router.post("/argocd/run")
def run_argocd(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return collect_from_argocd(db)


@router.post("/zabbix/run")
def run_zabbix(db: Session = Depends(get_db), user=Depends(get_current_user)):
    collect_from_zabbix(db)
    return {"status": "OK", "integration": "ZABBIX"}


@router.post("/vmware/run")
def run_vmware(db: Session = Depends(get_db), user=Depends(get_current_user)):
    collect_from_vmware(db)
    return {"status": "OK", "integration": "VMWARE"}


@router.post("/jenkins/run")
def run_jenkins(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return collect_from_jenkins(db)


@router.post("/elasticsearch/run")
def run_elasticsearch(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return collect_from_elasticsearch(db)


@router.post("/kibana/discover")
def run_kibana_discovery(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return discover_kibana(db)


@router.post("/kibana/run")
def run_kibana(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return collect_from_kibana(db)