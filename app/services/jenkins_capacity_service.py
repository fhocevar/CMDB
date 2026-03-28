from datetime import datetime, timezone
import json
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.jenkins_client import JenkinsClient
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def _safe_percent(part: float | int, total: float | int) -> float:
    if not total or float(total) <= 0:
        return 0.0
    return round((float(part) / float(total)) * 100.0, 2)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip().replace("%", "")
            if not value:
                return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bytes_to_mb(value: Any) -> float | None:
    v = _safe_float(value)
    if v is None:
        return None
    return round(v / (1024 * 1024), 2)


def _bytes_to_gb(value: Any) -> float | None:
    v = _safe_float(value)
    if v is None:
        return None
    return round(v / (1024 * 1024 * 1024), 2)


def _extract_labels(computer: dict) -> list[str]:
    return [
        item.get("name")
        for item in (computer.get("assignedLabels") or [])
        if item.get("name")
    ]


def _find_monitor_entry(monitor_data: dict, keywords: list[str]) -> dict | None:
    for key, value in (monitor_data or {}).items():
        if not isinstance(value, dict):
            continue
        key_lower = str(key).lower()
        for keyword in keywords:
            if keyword.lower() in key_lower:
                return value
    return None


def _extract_memory_metrics(monitor_data: dict) -> dict:
    mem = _find_monitor_entry(
        monitor_data,
        ["swap space", "memory", "memory monitor", "swap"],
    )

    memory_total_mb = None
    memory_free_mb = None
    memory_used_mb = None
    memory_used_pct = None

    if mem:
        total_physical = (
            mem.get("totalPhysicalMemory")
            or mem.get("totalMemory")
            or mem.get("total")
        )
        available_physical = (
            mem.get("availablePhysicalMemory")
            or mem.get("availableMemory")
            or mem.get("free")
        )

        memory_total_mb = _bytes_to_mb(total_physical)
        memory_free_mb = _bytes_to_mb(available_physical)

        if memory_total_mb is not None and memory_free_mb is not None:
            memory_used_mb = round(memory_total_mb - memory_free_mb, 2)
            memory_used_pct = _safe_percent(memory_used_mb, memory_total_mb)

    return {
        "memory_total_mb": memory_total_mb or 0.0,
        "memory_used_mb": memory_used_mb or 0.0,
        "memory_free_mb": memory_free_mb or 0.0,
        "memory_used_pct": memory_used_pct or 0.0,
    }


def _extract_disk_metrics(monitor_data: dict) -> dict:
    disk = _find_monitor_entry(
        monitor_data,
        ["disk space", "diskspace", "temporary space", "temporaryspace"],
    )

    disk_total_gb = None
    disk_free_gb = None
    disk_used_gb = None
    disk_used_pct = None

    if disk:
        total_size = (
            disk.get("totalSize")
            or disk.get("size")
            or disk.get("total")
            or disk.get("totalSpace")
        )
        available_size = (
            disk.get("availableSize")
            or disk.get("freeSize")
            or disk.get("free")
            or disk.get("usableSpace")
        )

        disk_total_gb = _bytes_to_gb(total_size)
        disk_free_gb = _bytes_to_gb(available_size)

        if disk_total_gb is not None and disk_free_gb is not None:
            disk_used_gb = round(disk_total_gb - disk_free_gb, 2)
            disk_used_pct = _safe_percent(disk_used_gb, disk_total_gb)

    return {
        "disk_total_gb": disk_total_gb or 0.0,
        "disk_used_gb": disk_used_gb or 0.0,
        "disk_free_gb": disk_free_gb or 0.0,
        "disk_used_pct": disk_used_pct or 0.0,
    }


def _extract_cpu_metrics(monitor_data: dict) -> dict:
    cpu_load_pct = None
    response_time_ms = None

    for key, value in (monitor_data or {}).items():
        if not isinstance(value, dict):
            continue

        key_lower = str(key).lower()

        if "load" in key_lower or "architecture" in key_lower or "cpu" in key_lower:
            raw = (
                value.get("systemAverageLoad")
                or value.get("averageLoad")
                or value.get("load")
                or value.get("cpuUsage")
            )
            cpu_load_pct = _safe_float(raw)
            if cpu_load_pct is not None and cpu_load_pct <= 1:
                cpu_load_pct = round(cpu_load_pct * 100.0, 2)
            elif cpu_load_pct is not None:
                cpu_load_pct = round(cpu_load_pct, 2)

        if "response" in key_lower:
            response_time_ms = _safe_float(
                value.get("average") or value.get("responseTime") or value.get("value")
            )

    return {
        "cpu_load_pct": cpu_load_pct or 0.0,
        "response_time_ms": response_time_ms or 0.0,
    }


def _agent_status(
    offline: bool,
    temp_offline: bool,
    usage_percent: float,
    cpu_percent: float,
    memory_percent: float,
    disk_percent: float,
) -> str:
    if offline or temp_offline:
        return "critical"
    if usage_percent >= 90 or cpu_percent >= 90 or memory_percent >= 92 or disk_percent >= 92:
        return "critical"
    if usage_percent >= 80 or cpu_percent >= 80 or memory_percent >= 85 or disk_percent >= 85:
        return "warning"
    return "ok"


def _overall_status(
    agents_offline: int,
    queue_stuck: int,
    queue_blocked: int,
    queue_oldest_wait_sec: float,
    executor_usage_percent: float,
    agents_high_cpu: int,
    agents_high_memory: int,
    agents_low_disk: int,
) -> str:
    if agents_offline > 0 or queue_stuck > 0 or executor_usage_percent >= 90:
        return "critical"

    if (
        queue_blocked > 0
        or queue_oldest_wait_sec >= 60
        or executor_usage_percent >= 80
        or agents_high_cpu > 0
        or agents_high_memory > 0
        or agents_low_disk > 0
    ):
        return "warning"

    return "ok"


def collect_from_jenkins(db: Session) -> dict:
    try:
        client = JenkinsClient()
        computers = client.list_computers()
        queue_items = client.get_queue()
    except Exception as exc:
        return {
            "status": "ERROR",
            "integration": "JENKINS",
            "message": str(exc),
        }

    total_agents = 0
    metrics_written = 0

    executors_total = 0
    executors_busy = 0
    executors_idle = 0
    agents_offline = 0
    agents_temp_offline = 0
    agents_high_cpu = 0
    agents_high_memory = 0
    agents_low_disk = 0
    saturation_agents_total = 0

    collected_at = datetime.utcnow()
    top_agents = []

    for computer in computers:
        name = computer.get("displayName")
        if not name:
            continue

        if name.lower() in {"built-in node", "master"}:
            asset_type = "JENKINS_CONTROLLER"
        else:
            asset_type = "JENKINS_AGENT"

        num_executors = int(computer.get("numExecutors") or 0)
        busy_executors = int(computer.get("busyExecutors") or 0)

        idle_executors_raw = computer.get("idleExecutors")
        if idle_executors_raw is None:
            idle_executors = max(num_executors - busy_executors, 0)
        else:
            idle_executors = int(idle_executors_raw or 0)

        offline = bool(computer.get("offline"))
        temp_offline = bool(computer.get("temporarilyOffline"))

        labels = _extract_labels(computer)
        usage_percent = _safe_percent(busy_executors, num_executors)

        monitor_data = computer.get("monitorData") or {}
        memory = _extract_memory_metrics(monitor_data)
        disk = _extract_disk_metrics(monitor_data)
        cpu = _extract_cpu_metrics(monitor_data)

        if offline:
            agents_offline += 1
        if temp_offline:
            agents_temp_offline += 1
        if cpu["cpu_load_pct"] >= 80:
            agents_high_cpu += 1
        if memory["memory_used_pct"] >= 85:
            agents_high_memory += 1
        if disk["disk_used_pct"] >= 85:
            agents_low_disk += 1
        if usage_percent >= 80:
            saturation_agents_total += 1

        executors_total += num_executors
        executors_busy += busy_executors
        executors_idle += idle_executors

        agent_status = _agent_status(
            offline=offline,
            temp_offline=temp_offline,
            usage_percent=usage_percent,
            cpu_percent=cpu["cpu_load_pct"],
            memory_percent=memory["memory_used_pct"],
            disk_percent=disk["disk_used_pct"],
        )

        top_agents.append(
            {
                "name": name,
                "busy_executors": busy_executors,
                "total_executors": num_executors,
                "idle_executors": idle_executors,
                "executor_usage_percent": usage_percent,
                "cpu_load_percent": cpu["cpu_load_pct"],
                "memory_used_percent": memory["memory_used_pct"],
                "disk_used_percent": disk["disk_used_pct"],
                "offline": offline,
                "temporarily_offline": temp_offline,
                "status": agent_status,
                "monitor_keys": list((monitor_data or {}).keys()),
            }
        )

        asset, _ = upsert_asset(
            db,
            AssetCreate(
                hostname=f"jenkins-{name}".replace(" ", "-").lower(),
                asset_type=asset_type,
                environment="PRD",
                criticality="ALTA",
                business_service="JENKINS",
                ip_address=None,
                operating_system="UNKNOWN",
                cpu_cores=max(num_executors, 1),
                memory_gb=round(memory["memory_total_mb"] / 1024, 2) if memory["memory_total_mb"] else 0,
                disk_gb=disk["disk_total_gb"],
                network_mbps=0,
                cluster_name=None,
                namespace=None,
                source="JENKINS",
                provider="JENKINS",
                external_id=name,
                labels_json=json.dumps(
                    {
                        "description": computer.get("description"),
                        "labels": labels,
                        "monitorData": monitor_data,
                    },
                    ensure_ascii=False,
                ),
                is_active=not offline,
            ),
        )

        metrics = [
            ("jenkins_executor_usage_percent", usage_percent, "percent"),
            ("jenkins_busy_executors", busy_executors, "count"),
            ("jenkins_idle_executors", idle_executors, "count"),
            ("jenkins_total_executors", num_executors, "count"),
            ("jenkins_offline_state", 100.0 if offline else 0.0, "state"),
            ("jenkins_temp_offline_state", 100.0 if temp_offline else 0.0, "state"),
            ("jenkins_cpu_load_percent", cpu["cpu_load_pct"], "percent"),
            ("jenkins_memory_used_percent", memory["memory_used_pct"], "percent"),
            ("jenkins_memory_used_mb", memory["memory_used_mb"], "mb"),
            ("jenkins_memory_free_mb", memory["memory_free_mb"], "mb"),
            ("jenkins_memory_total_mb", memory["memory_total_mb"], "mb"),
            ("jenkins_disk_used_percent", disk["disk_used_pct"], "percent"),
            ("jenkins_disk_used_gb", disk["disk_used_gb"], "gb"),
            ("jenkins_disk_free_gb", disk["disk_free_gb"], "gb"),
            ("jenkins_disk_total_gb", disk["disk_total_gb"], "gb"),
            ("jenkins_response_time_ms", cpu["response_time_ms"], "ms"),
        ]

        for metric_type, metric_value, metric_unit in metrics:
            ingest_metric(
                db,
                MetricCreate(
                    asset_id=asset.id,
                    metric_type=metric_type,
                    metric_value=float(metric_value or 0),
                    metric_unit=metric_unit,
                    collected_at=collected_at,
                    source="JENKINS",
                ),
            )
            update_baseline(db, asset.id, metric_type)
            metrics_written += 1

        total_agents += 1

    queue_total = len(queue_items)
    queue_buildable = sum(1 for item in queue_items if item.get("buildable"))
    queue_blocked = sum(1 for item in queue_items if item.get("blocked"))
    queue_stuck = sum(1 for item in queue_items if item.get("stuck"))

    waits = []
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    for item in queue_items:
        in_queue_since = item.get("inQueueSince")
        if in_queue_since:
            waits.append(max(0, (now_ms - int(in_queue_since)) / 1000.0))

    queue_oldest_wait_sec = round(max(waits), 2) if waits else 0.0
    queue_pending_duration_avg_sec = round(sum(waits) / len(waits), 2) if waits else 0.0

    executor_usage_percent = _safe_percent(executors_busy, executors_total)
    overall_status = _overall_status(
        agents_offline=agents_offline,
        queue_stuck=queue_stuck,
        queue_blocked=queue_blocked,
        queue_oldest_wait_sec=queue_oldest_wait_sec,
        executor_usage_percent=executor_usage_percent,
        agents_high_cpu=agents_high_cpu,
        agents_high_memory=agents_high_memory,
        agents_low_disk=agents_low_disk,
    )

    summary_asset, _ = upsert_asset(
        db,
        AssetCreate(
            hostname="jenkins-platform",
            asset_type="JENKINS_PLATFORM",
            environment="PRD",
            criticality="ALTA",
            business_service="JENKINS",
            ip_address=None,
            operating_system="UNKNOWN",
            cpu_cores=max(executors_total, 1),
            memory_gb=0,
            disk_gb=0,
            network_mbps=0,
            cluster_name=None,
            namespace=None,
            source="JENKINS",
            provider="JENKINS",
            external_id="jenkins-platform",
            labels_json=json.dumps(
                {
                    "queue_total": queue_total,
                    "queue_buildable": queue_buildable,
                    "queue_blocked": queue_blocked,
                    "queue_stuck": queue_stuck,
                    "overall_status": overall_status,
                },
                ensure_ascii=False,
            ),
            is_active=True,
        ),
    )

    summary_metrics = [
        ("jenkins_platform_executor_usage_percent", executor_usage_percent, "percent"),
        ("jenkins_platform_total_executors", executors_total, "count"),
        ("jenkins_platform_busy_executors", executors_busy, "count"),
        ("jenkins_platform_idle_executors", executors_idle, "count"),
        ("jenkins_platform_agents_total", total_agents, "count"),
        ("jenkins_platform_agents_offline", agents_offline, "count"),
        ("jenkins_platform_agents_temp_offline", agents_temp_offline, "count"),
        ("jenkins_platform_agents_high_cpu", agents_high_cpu, "count"),
        ("jenkins_platform_agents_high_memory", agents_high_memory, "count"),
        ("jenkins_platform_agents_low_disk", agents_low_disk, "count"),
        ("jenkins_platform_saturation_agents_total", saturation_agents_total, "count"),
        ("jenkins_platform_queue_total", queue_total, "count"),
        ("jenkins_platform_queue_buildable", queue_buildable, "count"),
        ("jenkins_platform_queue_blocked", queue_blocked, "count"),
        ("jenkins_platform_queue_stuck", queue_stuck, "count"),
        ("jenkins_platform_queue_oldest_wait_sec", queue_oldest_wait_sec, "seconds"),
        ("jenkins_platform_queue_pending_duration_avg_sec", queue_pending_duration_avg_sec, "seconds"),
    ]

    for metric_type, metric_value, metric_unit in summary_metrics:
        ingest_metric(
            db,
            MetricCreate(
                asset_id=summary_asset.id,
                metric_type=metric_type,
                metric_value=float(metric_value or 0),
                metric_unit=metric_unit,
                collected_at=collected_at,
                source="JENKINS",
            ),
        )
        update_baseline(db, summary_asset.id, metric_type)
        metrics_written += 1

    top_agents_filtered = [
        agent for agent in top_agents
        if agent["name"].lower() not in {"master", "built-in node"}
    ]

    top_agents = sorted(
        top_agents_filtered,
        key=lambda x: (
            0 if x["status"] == "critical" else 1 if x["status"] == "warning" else 2,
            -x["executor_usage_percent"],
            -x["cpu_load_percent"],
            -x["memory_used_percent"],
        ),
    )[:5]

    limitations = []

    if all(not agent.get("monitor_keys") for agent in top_agents):
        limitations = [
            "As métricas de CPU, memória e disco vieram vazias.",
            "O Jenkins não retornou monitorData para os agents.",
            "A coleta dessas métricas via Jenkins pode exigir permissões adicionais ou configuração de monitoramento nos nodes.",
            "A coleta pode ser impactada por falta de permissões administrativas.",
            "Execuções via Jenkins podem usar usuário de serviço (ex: SYSTEM), afetando os dados coletados.",
            "Coleta remota (WinRM) pode falhar ou retornar dados parciais se não estiver corretamente configurada.",
            "Restrições de rede, proxy ou firewall podem impedir a coleta completa.",
            "Serviços do sistema (WMI/Performance Counters) podem não estar disponíveis ou ativos.",
            "Integrações com APIs dependem de autenticação e permissões válidas.",
            "Ambientes virtualizados ou instabilidade podem causar variações nas métricas.",
            "Diferenças no contexto de execução (local, remoto ou container) podem impactar os resultados."
        ]

    return {
        "status": "OK",
        "integration": "JENKINS",
        "agents_collected": total_agents,
        "metrics_written": metrics_written,
        "summary": {
            "agents_total": total_agents,
            "agents_online": total_agents - agents_offline,
            "agents_offline": agents_offline,
            "agents_temp_offline": agents_temp_offline,
            "executors_total": executors_total,
            "executors_busy": executors_busy,
            "executors_idle": executors_idle,
            "executor_usage_percent": executor_usage_percent,
            "queue_total": queue_total,
            "queue_buildable": queue_buildable,
            "queue_blocked": queue_blocked,
            "queue_stuck": queue_stuck,
            "queue_oldest_wait_sec": queue_oldest_wait_sec,
            "queue_pending_duration_avg_sec": queue_pending_duration_avg_sec,
            "agents_high_cpu": agents_high_cpu,
            "agents_high_memory": agents_high_memory,
            "agents_low_disk": agents_low_disk,
            "saturated_agents": saturation_agents_total,
            "overall_status": overall_status,
        },
        "top_agents": top_agents,
        "limitations": limitations,
    }