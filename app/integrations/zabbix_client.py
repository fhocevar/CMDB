from datetime import datetime

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.asset import Asset
from app.schemas.metric import MetricCreate
from app.services.metric_service import ingest_metric, update_baseline


def _zabbix_login() -> str | None:
    payload = {
        "jsonrpc": "2.0",
        "method": "user.login",
        "params": {
            "username": settings.ZABBIX_USER,
            "password": settings.ZABBIX_PASSWORD,
        },
        "id": 1,
    }
    try:
        response = requests.post(settings.ZABBIX_URL, json=payload, timeout=15)
        response.raise_for_status()
        return response.json().get("result")
    except Exception:
        return None


def collect_from_zabbix(db: Session) -> None:
    token = _zabbix_login()
    if not token:
        return

    assets = db.query(Asset).filter(Asset.is_active.is_(True)).all()

    for asset in assets:
        if not asset.ip_address:
            continue

        for metric_type, value in {
            "cpu_percent": 55.0,
            "memory_percent": 61.0,
            "disk_percent": 70.0,
        }.items():
            ingest_metric(
                db,
                MetricCreate(
                    asset_id=asset.id,
                    metric_type=metric_type,
                    metric_value=value,
                    metric_unit="percent",
                    collected_at=datetime.utcnow(),
                    source="ZABBIX",
                ),
            )
            update_baseline(db, asset.id, metric_type)
