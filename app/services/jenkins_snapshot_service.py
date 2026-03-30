from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.jenkins_capacity_service import collect_from_jenkins


def _avg(values: list[float]) -> float:
    valid = [float(v) for v in values if v is not None]
    if not valid:
        return 0.0
    return round(sum(valid) / len(valid), 2)


def _min_value(values: list[float]) -> float:
    valid = [float(v) for v in values if v is not None]
    if not valid:
        return 0.0
    return round(min(valid), 2)


def build_jenkins_capacity_snapshot(db: Session) -> dict[str, Any]:
    result = collect_from_jenkins(db)

    if result.get("status") != "OK":
        return {
            "status": "ERROR",
            "provider": "JENKINS",
            "message": result.get("message", "Erro ao coletar snapshot do Jenkins."),
        }

    top_agents = result.get("top_agents", [])
    summary = result.get("summary", {})
    limitations = result.get("limitations", [])

    cpu_operational_values = [
        agent.get("cpu_operational_percent", 0)
        for agent in top_agents
    ]
    memory_used_values = [
        agent.get("memory_used_percent", 0)
        for agent in top_agents
        if agent.get("memory_has_real_data")
    ]
    disk_free_values = [
        agent.get("disk_free_gb", 0)
        for agent in top_agents
        if agent.get("disk_has_real_data")
    ]

    alerts: list[dict[str, Any]] = []

    for agent in top_agents:
        if agent.get("offline"):
            alerts.append({
                "severity": "critical",
                "type": "agent_offline",
                "agent": agent.get("name"),
                "message": f"Agent {agent.get('name')} está offline.",
            })

        if agent.get("disk_has_real_data") and agent.get("disk_free_gb", 0) <= 5:
            alerts.append({
                "severity": "critical",
                "type": "low_disk",
                "agent": agent.get("name"),
                "message": f"Agent {agent.get('name')} com disco crítico: {agent.get('disk_free_gb')} GB livres.",
            })
        elif agent.get("disk_has_real_data") and agent.get("disk_free_gb", 0) <= 10:
            alerts.append({
                "severity": "warning",
                "type": "low_disk",
                "agent": agent.get("name"),
                "message": f"Agent {agent.get('name')} com pouco disco: {agent.get('disk_free_gb')} GB livres.",
            })

        if agent.get("memory_has_real_data") and agent.get("memory_used_percent", 0) >= 95:
            alerts.append({
                "severity": "critical",
                "type": "high_memory",
                "agent": agent.get("name"),
                "message": f"Agent {agent.get('name')} com memória crítica: {agent.get('memory_used_percent')}%.",
            })
        elif agent.get("memory_has_real_data") and agent.get("memory_used_percent", 0) >= 90:
            alerts.append({
                "severity": "warning",
                "type": "high_memory",
                "agent": agent.get("name"),
                "message": f"Agent {agent.get('name')} com memória alta: {agent.get('memory_used_percent')}%.",
            })

        if agent.get("cpu_operational_percent", 0) >= 95:
            alerts.append({
                "severity": "critical",
                "type": "high_cpu_operational",
                "agent": agent.get("name"),
                "message": f"Agent {agent.get('name')} com CPU operacional crítica: {agent.get('cpu_operational_percent')}%.",
            })
        elif agent.get("cpu_operational_percent", 0) >= 85:
            alerts.append({
                "severity": "warning",
                "type": "high_cpu_operational",
                "agent": agent.get("name"),
                "message": f"Agent {agent.get('name')} com CPU operacional alta: {agent.get('cpu_operational_percent')}%.",
            })

    if summary.get("queue_blocked", 0) > 0:
        alerts.append({
            "severity": "warning",
            "type": "queue_blocked",
            "agent": None,
            "message": f"Fila do Jenkins com {summary.get('queue_blocked')} item(ns) bloqueado(s).",
        })

    agents_snapshot = []
    for agent in top_agents:
        agents_snapshot.append({
            "name": agent.get("name"),
            "status": agent.get("status"),
            "offline": agent.get("offline"),
            "temporarily_offline": agent.get("temporarily_offline"),
            "busy_executors": agent.get("busy_executors"),
            "total_executors": agent.get("total_executors"),
            "idle_executors": agent.get("idle_executors"),
            "executor_usage_percent": agent.get("executor_usage_percent"),
            "cpu_load_percent": agent.get("cpu_load_percent"),
            "cpu_operational_percent": agent.get("cpu_operational_percent"),
            "cpu_has_real_data": agent.get("cpu_has_real_data"),
            "memory_used_percent": agent.get("memory_used_percent"),
            "memory_total_gb": agent.get("memory_total_gb"),
            "memory_available_gb": agent.get("memory_available_gb"),
            "memory_has_real_data": agent.get("memory_has_real_data"),
            "disk_free_gb": agent.get("disk_free_gb"),
            "disk_total_gb": agent.get("disk_total_gb"),
            "disk_has_real_data": agent.get("disk_has_real_data"),
            "disk_path": agent.get("disk_path"),
            "disk_source": agent.get("disk_source"),
        })

    return {
        "status": "OK",
        "provider": "JENKINS",
        "snapshot_type": "jenkins_capacity",
        "summary": {
            "agents_total": summary.get("agents_total", 0),
            "agents_online": summary.get("agents_online", 0),
            "agents_offline": summary.get("agents_offline", 0),
            "agents_temp_offline": summary.get("agents_temp_offline", 0),
            "executors_total": summary.get("executors_total", 0),
            "executors_busy": summary.get("executors_busy", 0),
            "executors_idle": summary.get("executors_idle", 0),
            "executor_usage_percent": summary.get("executor_usage_percent", 0),
            "queue_total": summary.get("queue_total", 0),
            "queue_blocked": summary.get("queue_blocked", 0),
            "queue_stuck": summary.get("queue_stuck", 0),
            "overall_status": summary.get("overall_status", "ok"),
            "has_real_cpu_data": summary.get("has_real_cpu_data", False),
            "has_real_memory_data": summary.get("has_real_memory_data", False),
            "has_real_disk_data": summary.get("has_real_disk_data", False),
            "avg_cpu_operational_percent": _avg(cpu_operational_values),
            "avg_memory_used_percent": _avg(memory_used_values),
            "min_disk_free_gb": _min_value(disk_free_values),
        },
        "alerts": alerts,
        "agents": agents_snapshot,
        "limitations": limitations,
    }