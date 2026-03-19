from sqlalchemy.orm import Session

from app.core.config import settings
from app.discovery.ping_discovery import discover_by_ping
from app.discovery.snmp_discovery import discover_by_snmp
from app.discovery.ssh_discovery import discover_by_ssh
from app.services.discovery_service import create_discovery_job, finalize_discovery_job, persist_discovered_assets


def run_discovery_cycle(db: Session) -> dict:
    job = create_discovery_job(db, "DISCOVERY_CYCLE")
    all_assets = []

    try:
        ping_assets = discover_by_ping() if settings.DISCOVERY_PING_ENABLED else []
        all_assets.extend(ping_assets)

        ip_list = [item.ip_address for item in ping_assets if item.ip_address]

        if settings.DISCOVERY_SSH_ENABLED and ip_list:
            all_assets.extend(discover_by_ssh(ip_list))

        if settings.DISCOVERY_SNMP_ENABLED and ip_list:
            all_assets.extend(discover_by_snmp(ip_list))

        created_count, updated_count = persist_discovered_assets(db, all_assets)

        finalize_discovery_job(
            db=db,
            job=job,
            status="SUCCESS",
            assets_found=created_count,
            assets_updated=updated_count,
        )

        return {
            "status": "SUCCESS",
            "assets_found": created_count,
            "assets_updated": updated_count,
        }
    except Exception as exc:
        finalize_discovery_job(
            db=db,
            job=job,
            status="FAILED",
            assets_found=0,
            assets_updated=0,
            error_message=str(exc),
        )
        return {"status": "FAILED", "message": str(exc)}
