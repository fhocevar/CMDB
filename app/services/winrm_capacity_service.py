from datetime import datetime
import json

from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.winrm_client import WinRMClient
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def collect_from_winrm(db: Session, hosts: list[str]) -> dict:
    """
    Coleta métricas de infraestrutura via WinRM:
    - CPU
    - Memória
    - Disco
    """

    if not settings.WINRM_ENABLED:
        return {
            "status": "SKIPPED",
            "integration": "WINRM",
            "message": "WINRM está desabilitado.",
        }

    client = WinRMClient()

    total_hosts = 0
    success_hosts = 0
    error_hosts = 0
    metrics_written = 0

    collected_at = datetime.utcnow()
    host_results = []

    for host in hosts:
        total_hosts += 1

        try:
            metrics = client.get_windows_system_metrics(host)

            cpu = float(metrics.get("cpu_load_percent") or 0.0)
            memory_total_mb = float(metrics.get("memory_total_mb") or 0.0)
            memory_used_mb = float(metrics.get("memory_used_mb") or 0.0)
            memory_free_mb = float(metrics.get("memory_free_mb") or 0.0)
            memory_used_pct = float(metrics.get("memory_used_percent") or 0.0)
            disk_total_gb = float(metrics.get("disk_total_gb") or 0.0)
            disk_used_gb = float(metrics.get("disk_used_gb") or 0.0)
            disk_free_gb = float(metrics.get("disk_free_gb") or 0.0)
            disk_used_pct = float(metrics.get("disk_used_percent") or 0.0)
            os_name = metrics.get("os_name") or "WINDOWS"

            success_hosts += 1

            # 🔹 UPSERT ASSET
            asset, _ = upsert_asset(
                db,
                AssetCreate(
                    hostname=host.lower(),
                    asset_type="SERVER",
                    environment="PRD",
                    criticality="ALTA",
                    business_service="INFRA",
                    ip_address=None,
                    operating_system=os_name,
                    cpu_cores=0,
                    memory_gb=round(memory_total_mb / 1024, 2) if memory_total_mb else 0,
                    disk_gb=disk_total_gb,
                    network_mbps=0,
                    cluster_name=None,
                    namespace=None,
                    source="WINRM",
                    provider="WINRM",
                    external_id=host,
                    labels_json=json.dumps({}, ensure_ascii=False),
                    is_active=True,
                ),
            )

            # 🔹 MÉTRICAS
            metric_list = [
                ("winrm_cpu_load_percent", cpu, "percent"),
                ("winrm_memory_used_percent", memory_used_pct, "percent"),
                ("winrm_memory_used_mb", memory_used_mb, "mb"),
                ("winrm_memory_free_mb", memory_free_mb, "mb"),
                ("winrm_memory_total_mb", memory_total_mb, "mb"),
                ("winrm_disk_used_percent", disk_used_pct, "percent"),
                ("winrm_disk_used_gb", disk_used_gb, "gb"),
                ("winrm_disk_free_gb", disk_free_gb, "gb"),
                ("winrm_disk_total_gb", disk_total_gb, "gb"),
            ]

            for metric_type, metric_value, metric_unit in metric_list:
                ingest_metric(
                    db,
                    MetricCreate(
                        asset_id=asset.id,
                        metric_type=metric_type,
                        metric_value=float(metric_value or 0),
                        metric_unit=metric_unit,
                        collected_at=collected_at,
                        source="WINRM",
                    ),
                )
                update_baseline(db, asset.id, metric_type)
                metrics_written += 1

            host_results.append(
                {
                    "host": host,
                    "status": "OK",
                    "cpu_load_percent": cpu,
                    "memory_used_percent": memory_used_pct,
                    "disk_used_percent": disk_used_pct,
                }
            )

        except Exception as exc:
            error_hosts += 1

            host_results.append(
                {
                    "host": host,
                    "status": "ERROR",
                    "message": str(exc),
                }
            )

    # 🔹 SUMMARY
    summary = {
        "hosts_total": total_hosts,
        "hosts_success": success_hosts,
        "hosts_error": error_hosts,
    }

    # 🔹 LIMITATIONS
    limitations = []

    if error_hosts > 0:
        limitations.append(
            "Um ou mais hosts falharam na coleta via WinRM. Verifique conectividade, credenciais e permissões."
        )

    if total_hosts == 0:
        limitations.append(
            "Nenhum host foi informado para coleta WinRM."
        )

    return {
        "status": "OK" if error_hosts == 0 else "PARTIAL",
        "integration": "WINRM",
        "hosts_collected": total_hosts,
        "metrics_written": metrics_written,
        "summary": summary,
        "hosts": host_results,
        "limitations": limitations,
    }