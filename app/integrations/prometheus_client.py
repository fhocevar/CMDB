from datetime import datetime

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.asset import Asset
from app.schemas.metric import MetricCreate
from app.services.metric_service import ingest_metric, update_baseline

PROM_QUERY_MAP = {
    "cpu_percent": '100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
    "memory_percent": '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100',
    "disk_percent": '(1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100',
}


def _query_prometheus(query: str) -> list[dict]:
    response = requests.get(
        f"{settings.PROMETHEUS_URL}/api/v1/query",
        params={"query": query},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("data", {}).get("result", [])


def collect_from_prometheus(db: Session) -> None:
    assets = db.query(Asset).filter(Asset.is_active.is_(True)).all()

    for metric_type, prom_query in PROM_QUERY_MAP.items():
        try:
            results = _query_prometheus(prom_query)
        except Exception:
            continue

        for item in results:
            instance = item.get("metric", {}).get("instance", "")
            value = float(item.get("value", [0, 0])[1])

            for asset in assets:
                if asset.ip_address and asset.ip_address in instance:
                    ingest_metric(
                        db,
                        MetricCreate(
                            asset_id=asset.id,
                            metric_type=metric_type,
                            metric_value=round(value, 2),
                            metric_unit="percent",
                            collected_at=datetime.utcnow(),
                            source="PROMETHEUS",
                        ),
                    )
                    update_baseline(db, asset.id, metric_type)
