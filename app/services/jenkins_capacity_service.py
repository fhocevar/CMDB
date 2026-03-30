from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.jenkins_client import JenkinsClient
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def _safe_percent(part: float | int, total: float | int) -> float:
    try:
        part = float(part or 0)
        total = float(total or 0)
        if total <= 0:
            return 0.0
        return round((part / total) * 100, 2)
    except Exception:
        return 0.0


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def _bytes_to_gb(value: float | int | None) -> float:
    if value is None:
        return 0.0
    try:
        return round(float(value) / (1024 ** 3), 2)
    except Exception:
        return 0.0


def _normalize_monitor_data(monitor_data: Any) -> dict[str, Any]:
    if isinstance(monitor_data, dict):
        return monitor_data
    return {}


def _find_monitor_entry(monitor_data: dict[str, Any], contains_terms: list[str]) -> tuple[str | None, Any]:
    for key, value in monitor_data.items():
        key_lower = str(key).lower()
        if all(term.lower() in key_lower for term in contains_terms):
            return key, value
    return None, None


def _walk_scalars(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []

    if isinstance(value, dict):
        for k, v in value.items():
            next_prefix = f"{prefix}.{k}" if prefix else str(k)
            items.extend(_walk_scalars(v, next_prefix))
        return items

    if isinstance(value, list):
        for idx, v in enumerate(value):
            next_prefix = f"{prefix}[{idx}]"
            items.extend(_walk_scalars(v, next_prefix))
        return items

    items.append((prefix.lower(), value))
    return items


def _pick_first_numeric_by_name(entry: Any, candidate_names: list[str]) -> float | None:
    flattened = _walk_scalars(entry)
    candidate_names = [c.lower() for c in candidate_names]

    for path, value in flattened:
        for candidate in candidate_names:
            if candidate in path:
                parsed = _to_float(value)
                if parsed is not None:
                    return parsed
    return None


def _extract_memory_metrics(monitor_data: dict[str, Any]) -> dict[str, Any]:
    _, swap_entry = _find_monitor_entry(monitor_data, ["swap", "monitor"])

    if swap_entry is None:
        return {
            "memory_used_percent": 0.0,
            "memory_total_gb": 0.0,
            "memory_available_gb": 0.0,
            "memory_monitor_found": False,
            "memory_raw_type": None,
            "memory_has_real_data": False,
        }

    total_memory = _pick_first_numeric_by_name(
        swap_entry,
        [
            "totalphysicalmemory",
            "totalmemory",
            "total_memory",
            "totalbytes",
            "physicaltotal",
            "total",
        ],
    )

    available_memory = _pick_first_numeric_by_name(
        swap_entry,
        [
            "availablephysicalmemory",
            "availablememory",
            "available_memory",
            "freephysicalmemory",
            "freememory",
            "free_memory",
            "freebytes",
            "availablebytes",
            "free",
            "available",
        ],
    )

    used_percent = 0.0
    has_real_data = False

    if total_memory is not None and available_memory is not None and total_memory > 0:
        used_percent = round(((total_memory - available_memory) / total_memory) * 100, 2)
        has_real_data = True

    return {
        "memory_used_percent": used_percent,
        "memory_total_gb": _bytes_to_gb(total_memory),
        "memory_available_gb": _bytes_to_gb(available_memory),
        "memory_monitor_found": True,
        "memory_raw_type": type(swap_entry).__name__,
        "memory_has_real_data": has_real_data,
    }


def _extract_disk_metrics(monitor_data: dict[str, Any]) -> dict[str, Any]:
    """
    No Jenkins, DiskSpaceMonitor/TemporarySpaceMonitor retornam espaço LIVRE.
    O campo 'size' representa free/usable space do path monitorado.
    Não dá para calcular percentual sem o total do volume.
    """
    _, disk_entry = _find_monitor_entry(monitor_data, ["disk", "monitor"])
    _, temp_entry = _find_monitor_entry(monitor_data, ["temporary", "space", "monitor"])

    chosen_entry = disk_entry if disk_entry is not None else temp_entry
    chosen_source = "disk" if disk_entry is not None else ("temporary" if temp_entry is not None else None)

    if chosen_entry is None:
        return {
            "disk_used_percent": 0.0,
            "disk_total_gb": 0.0,
            "disk_free_gb": 0.0,
            "disk_monitor_found": False,
            "disk_raw_type": None,
            "disk_has_real_data": False,
            "disk_path": None,
            "disk_source": None,
        }

    free_size = _pick_first_numeric_by_name(
        chosen_entry,
        [
            "freesize",
            "usableSpace",
            "usablespace",
            "freebytes",
            "availablebytes",
            "availablesize",
            "size",
            "free",
            "available",
        ],
    )

    disk_path = None
    if isinstance(chosen_entry, dict):
        disk_path = chosen_entry.get("path")

    has_real_data = free_size is not None

    return {
        "disk_used_percent": 0.0,
        "disk_total_gb": 0.0,
        "disk_free_gb": _bytes_to_gb(free_size),
        "disk_monitor_found": True,
        "disk_raw_type": type(chosen_entry).__name__,
        "disk_has_real_data": has_real_data,
        "disk_path": disk_path,
        "disk_source": chosen_source,
    }


def _extract_cpu_metrics(
    monitor_data: dict[str, Any],
    total_executors: int,
    busy_executors: int,
) -> dict[str, Any]:
    _, cpu_entry = _find_monitor_entry(monitor_data, ["cpu"])
    if cpu_entry is None:
        _, load_entry = _find_monitor_entry(monitor_data, ["load"])
        cpu_entry = load_entry

    cpu_load_percent = 0.0
    has_real_data = False
    monitor_found = cpu_entry is not None
    raw_type = type(cpu_entry).__name__ if cpu_entry is not None else None

    if cpu_entry is not None:
        candidate = _pick_first_numeric_by_name(
            cpu_entry,
            [
                "cpuusage",
                "cpuload",
                "systemaverageload",
                "averageload",
                "load",
                "utilization",
                "usage",
            ],
        )

        if candidate is not None:
            if 0 <= candidate <= 1:
                cpu_load_percent = round(candidate * 100, 2)
            else:
                cpu_load_percent = round(candidate, 2)
            has_real_data = True

    cpu_operational_percent = _safe_percent(busy_executors, total_executors)

    if not has_real_data:
        cpu_load_percent = 0.0

    return {
        "cpu_load_percent": cpu_load_percent,
        "cpu_operational_percent": cpu_operational_percent,
        "cpu_monitor_found": monitor_found,
        "cpu_raw_type": raw_type,
        "cpu_has_real_data": has_real_data,
    }


def _collect_queue_stats(client: JenkinsClient) -> dict[str, Any]:
    default = {
        "queue_total": 0,
        "queue_buildable": 0,
        "queue_blocked": 0,
        "queue_stuck": 0,
        "queue_oldest_wait_sec": 0,
        "queue_pending_duration_avg_sec": 0,
    }

    try:
        queue_items = client.get_queue() or []
    except Exception:
        return default

    queue_total = len(queue_items)
    queue_buildable = sum(1 for item in queue_items if item.get("buildable"))
    queue_blocked = sum(1 for item in queue_items if item.get("blocked"))
    queue_stuck = sum(1 for item in queue_items if item.get("stuck"))

    waits = []
    for item in queue_items:
        in_queue_since = item.get("inQueueSince")
        if in_queue_since:
            try:
                now_ms = int(datetime.utcnow().timestamp() * 1000)
                wait_sec = max(0, round((now_ms - int(in_queue_since)) / 1000, 2))
                waits.append(wait_sec)
            except Exception:
                pass

    return {
        "queue_total": queue_total,
        "queue_buildable": queue_buildable,
        "queue_blocked": queue_blocked,
        "queue_stuck": queue_stuck,
        "queue_oldest_wait_sec": round(max(waits), 2) if waits else 0,
        "queue_pending_duration_avg_sec": round(sum(waits) / len(waits), 2) if waits else 0,
    }


def _sample_monitor_data(computers: list[dict[str, Any]]) -> dict[str, Any]:
    for computer in computers:
        name = computer.get("displayName")
        monitor_data = computer.get("monitorData") or {}
        if name and monitor_data:
            return {
                "agent": name,
                "monitor_keys": list(monitor_data.keys()) if isinstance(monitor_data, dict) else [],
                "monitorData": monitor_data,
            }

    return {
        "agent": None,
        "monitor_keys": [],
        "monitorData": {},
    }


def _build_overall_status(
    agents_offline: int,
    queue_blocked: int,
    queue_stuck: int,
    saturation_agents_total: int,
) -> str:
    if agents_offline > 0 or queue_stuck > 0 or saturation_agents_total > 0:
        return "critical"
    if queue_blocked > 0:
        return "warning"
    return "ok"


def collect_from_jenkins(db: Session) -> dict[str, Any]:
    try:
        client = JenkinsClient()
        computers = client.list_computers()
    except Exception as exc:
        return {
            "status": "ERROR",
            "integration": "JENKINS",
            "message": str(exc),
        }

    total_agents = 0
    metrics_written = 0

    agents_online = 0
    agents_offline = 0
    agents_temp_offline = 0

    executors_total = 0
    executors_busy = 0
    executors_idle = 0

    agents_high_cpu = 0
    agents_high_memory = 0
    agents_low_disk = 0
    saturation_agents_total = 0

    top_agents: list[dict[str, Any]] = []

    queue_stats = _collect_queue_stats(client)

    for computer in computers:
        name = computer.get("displayName")
        if not name:
            continue

        normalized_name = str(name).strip().lower()
        asset_type = "JENKINS_CONTROLLER" if normalized_name in {"built-in node", "master"} else "JENKINS_AGENT"

        num_executors = int(computer.get("numExecutors") or 0)
        busy_executors = int(computer.get("busyExecutors") or 0)

        idle_executors_api = _to_int(computer.get("idleExecutors"))
        idle_executors = max(idle_executors_api, 0) if idle_executors_api is not None else max(num_executors - busy_executors, 0)

        offline = bool(computer.get("offline"))
        temp_offline = bool(computer.get("temporarilyOffline"))

        monitor_data = _normalize_monitor_data(computer.get("monitorData"))
        monitor_keys = list(monitor_data.keys())

        labels = [
            item.get("name")
            for item in (computer.get("assignedLabels") or [])
            if item.get("name")
        ]

        executor_usage_percent = _safe_percent(busy_executors, num_executors)

        memory_metrics = _extract_memory_metrics(monitor_data)
        disk_metrics = _extract_disk_metrics(monitor_data)
        cpu_metrics = _extract_cpu_metrics(monitor_data, num_executors, busy_executors)

        cpu_load_percent = cpu_metrics["cpu_load_percent"]
        cpu_operational_percent = cpu_metrics["cpu_operational_percent"]
        memory_used_percent = memory_metrics["memory_used_percent"]
        disk_used_percent = disk_metrics["disk_used_percent"]

        if offline:
            agents_offline += 1
        else:
            agents_online += 1

        if temp_offline:
            agents_temp_offline += 1

        executors_total += num_executors
        executors_busy += busy_executors
        executors_idle += idle_executors

        if cpu_metrics["cpu_has_real_data"] and cpu_load_percent >= 85:
            agents_high_cpu += 1
        elif not cpu_metrics["cpu_has_real_data"] and cpu_operational_percent >= 85:
            agents_high_cpu += 1

        if memory_metrics["memory_has_real_data"] and memory_used_percent >= 90:
            agents_high_memory += 1

        if disk_metrics["disk_has_real_data"] and disk_metrics["disk_free_gb"] <= 10:
            agents_low_disk += 1

        agent_status = "ok"
        if offline or temp_offline:
            agent_status = "warning"

        if executor_usage_percent >= 95:
            agent_status = "critical"
            saturation_agents_total += 1
        elif executor_usage_percent >= 85 and agent_status != "critical":
            agent_status = "warning"

        if cpu_metrics["cpu_has_real_data"] and cpu_load_percent >= 95:
            agent_status = "critical"
        elif cpu_metrics["cpu_has_real_data"] and cpu_load_percent >= 85 and agent_status != "critical":
            agent_status = "warning"
        elif not cpu_metrics["cpu_has_real_data"] and cpu_operational_percent >= 95:
            agent_status = "critical"
        elif not cpu_metrics["cpu_has_real_data"] and cpu_operational_percent >= 85 and agent_status != "critical":
            agent_status = "warning"

        if memory_metrics["memory_has_real_data"] and memory_used_percent >= 95:
            agent_status = "critical"
        elif memory_metrics["memory_has_real_data"] and memory_used_percent >= 90 and agent_status != "critical":
            agent_status = "warning"

        if disk_metrics["disk_has_real_data"] and disk_metrics["disk_free_gb"] <= 5:
            agent_status = "critical"
        elif disk_metrics["disk_has_real_data"] and disk_metrics["disk_free_gb"] <= 10 and agent_status != "critical":
            agent_status = "warning"

        labels_json_payload = {
            "description": computer.get("description"),
            "labels": labels,
            "monitor_keys": monitor_keys,
            "monitorData": monitor_data,
            "memory_total_gb": memory_metrics["memory_total_gb"],
            "memory_available_gb": memory_metrics["memory_available_gb"],
            "disk_total_gb": disk_metrics["disk_total_gb"],
            "disk_free_gb": disk_metrics["disk_free_gb"],
            "disk_path": disk_metrics["disk_path"],
            "disk_source": disk_metrics["disk_source"],
            "memory_monitor_found": memory_metrics["memory_monitor_found"],
            "disk_monitor_found": disk_metrics["disk_monitor_found"],
            "cpu_monitor_found": cpu_metrics["cpu_monitor_found"],
            "memory_raw_type": memory_metrics["memory_raw_type"],
            "disk_raw_type": disk_metrics["disk_raw_type"],
            "cpu_raw_type": cpu_metrics["cpu_raw_type"],
            "memory_has_real_data": memory_metrics["memory_has_real_data"],
            "disk_has_real_data": disk_metrics["disk_has_real_data"],
            "cpu_has_real_data": cpu_metrics["cpu_has_real_data"],
            "cpu_operational_percent": cpu_operational_percent,
        }

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
                memory_gb=max(memory_metrics["memory_total_gb"], 0),
                disk_gb=0,
                network_mbps=0,
                cluster_name=None,
                namespace=None,
                source="JENKINS",
                provider="JENKINS",
                external_id=name,
                labels_json=json.dumps(labels_json_payload, ensure_ascii=False),
                is_active=not offline,
            ),
        )

        metrics = [
            ("jenkins_executor_usage_percent", executor_usage_percent, "percent"),
            ("jenkins_busy_executors", busy_executors, "count"),
            ("jenkins_idle_executors", idle_executors, "count"),
            ("jenkins_offline_state", 100.0 if offline else 0.0, "state"),
            ("jenkins_temp_offline_state", 100.0 if temp_offline else 0.0, "state"),
            ("jenkins_cpu_load_percent", cpu_load_percent, "percent"),
            ("jenkins_cpu_operational_percent", cpu_operational_percent, "percent"),
            ("jenkins_memory_used_percent", memory_used_percent, "percent"),
            ("jenkins_disk_used_percent", disk_used_percent, "percent"),
            ("jenkins_memory_total_gb", memory_metrics["memory_total_gb"], "gb"),
            ("jenkins_memory_available_gb", memory_metrics["memory_available_gb"], "gb"),
            ("jenkins_disk_free_gb", disk_metrics["disk_free_gb"], "gb"),
            ("jenkins_cpu_has_real_data", 100.0 if cpu_metrics["cpu_has_real_data"] else 0.0, "state"),
            ("jenkins_memory_has_real_data", 100.0 if memory_metrics["memory_has_real_data"] else 0.0, "state"),
            ("jenkins_disk_has_real_data", 100.0 if disk_metrics["disk_has_real_data"] else 0.0, "state"),
            ("jenkins_monitor_keys_count", len(monitor_keys), "count"),
            (
                "jenkins_agent_status_state",
                100.0 if agent_status == "critical" else (50.0 if agent_status == "warning" else 0.0),
                "state",
            ),
            ("jenkins_active_state", 0.0 if offline else 100.0, "state"),
            ("jenkins_labels_count", len(labels), "count"),
        ]

        for metric_type, metric_value, metric_unit in metrics:
            ingest_metric(
                db,
                MetricCreate(
                    asset_id=asset.id,
                    metric_type=metric_type,
                    metric_value=float(metric_value or 0),
                    metric_unit=metric_unit,
                    collected_at=datetime.utcnow(),
                    source="JENKINS",
                ),
            )
            update_baseline(db, asset.id, metric_type)
            metrics_written += 1

        top_agents.append(
            {
                "name": name,
                "busy_executors": busy_executors,
                "total_executors": num_executors,
                "idle_executors": idle_executors,
                "executor_usage_percent": executor_usage_percent,
                "cpu_load_percent": cpu_load_percent,
                "cpu_operational_percent": cpu_operational_percent,
                "memory_used_percent": memory_used_percent,
                "disk_used_percent": disk_used_percent,
                "memory_total_gb": memory_metrics["memory_total_gb"],
                "memory_available_gb": memory_metrics["memory_available_gb"],
                "disk_total_gb": disk_metrics["disk_total_gb"],
                "disk_free_gb": disk_metrics["disk_free_gb"],
                "disk_path": disk_metrics["disk_path"],
                "disk_source": disk_metrics["disk_source"],
                "cpu_has_real_data": cpu_metrics["cpu_has_real_data"],
                "memory_has_real_data": memory_metrics["memory_has_real_data"],
                "disk_has_real_data": disk_metrics["disk_has_real_data"],
                "offline": offline,
                "temporarily_offline": temp_offline,
                "status": agent_status,
                "monitor_keys": monitor_keys,
            }
        )

        total_agents += 1

    executor_usage_percent = _safe_percent(executors_busy, executors_total)

    overall_status = _build_overall_status(
        agents_offline=agents_offline,
        queue_blocked=queue_stats["queue_blocked"],
        queue_stuck=queue_stats["queue_stuck"],
        saturation_agents_total=saturation_agents_total,
    )

    top_agents = sorted(
        top_agents,
        key=lambda x: (
            x["status"] != "critical",
            x["status"] != "warning",
            -(x["memory_used_percent"] or 0),
            x["disk_free_gb"] if x["disk_free_gb"] > 0 else 999999,
            x["name"],
        ),
    )[:10]

    has_real_cpu_data = any(agent.get("cpu_has_real_data") for agent in top_agents)
    has_real_memory_data = any(agent.get("memory_has_real_data") for agent in top_agents)
    has_real_disk_data = any(agent.get("disk_has_real_data") for agent in top_agents)
    has_real_capacity_data = has_real_cpu_data or has_real_memory_data or has_real_disk_data

    limitations = []
    if not has_real_cpu_data:
        limitations.append("CPU real não foi disponibilizada pelo monitorData do Jenkins; CPU operacional usa ocupação dos executores.")
    if has_real_disk_data:
        limitations.append("Disco real disponível no Jenkins representa espaço livre do path monitorado; percentual de uso exige o tamanho total do volume.")
    else:
        limitations.append("Disco real não foi disponibilizado pelo monitorData do Jenkins.")
    if not has_real_memory_data:
        limitations.append("Memória real não foi disponibilizada pelo monitorData do Jenkins.")

    return {
        "status": "OK",
        "integration": "JENKINS",
        "agents_collected": total_agents,
        "metrics_written": metrics_written,
        "summary": {
            "agents_total": total_agents,
            "agents_online": agents_online,
            "agents_offline": agents_offline,
            "agents_temp_offline": agents_temp_offline,
            "executors_total": executors_total,
            "executors_busy": executors_busy,
            "executors_idle": executors_idle,
            "executor_usage_percent": executor_usage_percent,
            "queue_total": queue_stats["queue_total"],
            "queue_buildable": queue_stats["queue_buildable"],
            "queue_blocked": queue_stats["queue_blocked"],
            "queue_stuck": queue_stats["queue_stuck"],
            "queue_oldest_wait_sec": queue_stats["queue_oldest_wait_sec"],
            "queue_pending_duration_avg_sec": queue_stats["queue_pending_duration_avg_sec"],
            "agents_high_cpu": agents_high_cpu,
            "agents_high_memory": agents_high_memory,
            "agents_low_disk": agents_low_disk,
            "saturated_agents": saturation_agents_total,
            "overall_status": overall_status,
            "has_real_capacity_data": has_real_capacity_data,
            "has_real_cpu_data": has_real_cpu_data,
            "has_real_memory_data": has_real_memory_data,
            "has_real_disk_data": has_real_disk_data,
        },
        "top_agents": top_agents,
        "limitations": limitations,
        "monitor_data_sample": _sample_monitor_data(computers),
    }