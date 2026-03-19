from datetime import datetime

from sqlalchemy.orm import Session

from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def collect_from_vmware(db: Session) -> None:
    sample_vms = [
        {
            "hostname": "vm-app-01",
            "ip_address": "10.30.1.10",
            "cpu_percent": 49.0,
            "memory_percent": 68.0,
            "disk_percent": 57.0,
        }
    ]

    for vm in sample_vms:
        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=vm["hostname"],
                asset_type="VM",
                environment="PRD",
                criticality="ALTA",
                business_service="VMWARE",
                ip_address=vm["ip_address"],
                operating_system="LINUX",
                cpu_cores=4,
                memory_gb=16,
                disk_gb=100,
                network_mbps=1000,
                source="VMWARE",
            ),
        )

        for metric_type in ["cpu_percent", "memory_percent", "disk_percent"]:
            ingest_metric(
                db,
                MetricCreate(
                    asset_id=asset.id,
                    metric_type=metric_type,
                    metric_value=vm[metric_type],
                    metric_unit="percent",
                    collected_at=datetime.utcnow(),
                    source="VMWARE",
                ),
            )
            update_baseline(db, asset.id, metric_type)
