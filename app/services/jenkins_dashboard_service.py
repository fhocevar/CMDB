from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.jenkins_capacity_snapshot import JenkinsCapacitySnapshot
from app.services.jenkins_capacity_service import collect_from_jenkins


class JenkinsDashboardService:
    def __init__(self, db: Session):
        self.db = db

    def get_dashboard_data(self) -> dict[str, Any]:
        latest_snapshot = (
            self.db.query(JenkinsCapacitySnapshot)
            .order_by(JenkinsCapacitySnapshot.created_at.desc())
            .first()
        )

        if latest_snapshot:
            return self._build_dashboard_from_snapshot(latest_snapshot)

        return self._build_dashboard_from_live_data()

    def collect_and_persist_snapshot(self) -> dict[str, Any]:
        result = collect_from_jenkins(self.db)

        if result.get("status") != "OK":
            return {
                "status": "ERROR",
                "provider": "JENKINS",
                "message": result.get("message", "Erro ao coletar dados do Jenkins."),
            }

        summary = result.get("summary", {})
        top_agents = result.get("top_agents", [])
        limitations = result.get("limitations", [])

        avg_cpu_operational_percent = self._avg(
            [item.get("cpu_operational_percent", 0) for item in top_agents]
        )
        avg_memory_used_percent = self._avg(
            [item.get("memory_used_percent", 0) for item in top_agents if item.get("memory_has_real_data")]
        )
        min_disk_free_gb = self._min(
            [item.get("disk_free_gb", 0) for item in top_agents if item.get("disk_has_real_data")]
        )

        snapshot = JenkinsCapacitySnapshot(
            provider="JENKINS",
            snapshot_type="jenkins_capacity",
            overall_status=summary.get("overall_status"),
            agents_total=summary.get("agents_total"),
            agents_online=summary.get("agents_online"),
            agents_offline=summary.get("agents_offline"),
            agents_temp_offline=summary.get("agents_temp_offline"),
            executors_total=summary.get("executors_total"),
            executors_busy=summary.get("executors_busy"),
            executors_idle=summary.get("executors_idle"),
            queue_total=summary.get("queue_total"),
            queue_buildable=summary.get("queue_buildable"),
            queue_blocked=summary.get("queue_blocked"),
            queue_stuck=summary.get("queue_stuck"),
            executor_usage_percent=summary.get("executor_usage_percent"),
            avg_cpu_operational_percent=str(avg_cpu_operational_percent),
            avg_memory_used_percent=str(avg_memory_used_percent),
            min_disk_free_gb=str(min_disk_free_gb),
            has_real_cpu_data=str(summary.get("has_real_cpu_data", False)),
            has_real_memory_data=str(summary.get("has_real_memory_data", False)),
            has_real_disk_data=str(summary.get("has_real_disk_data", False)),
            summary_json=summary,
            agents_json=top_agents,
            limitations_json=limitations,
        )

        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)

        return {
            "status": "OK",
            "provider": "JENKINS",
            "message": "Snapshot do Jenkins persistido com sucesso.",
            "snapshot_id": snapshot.id,
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            "summary": summary,
        }

    def get_history(self, limit: int = 30) -> dict[str, Any]:
        rows = (
            self.db.query(JenkinsCapacitySnapshot)
            .order_by(JenkinsCapacitySnapshot.created_at.desc())
            .limit(limit)
            .all()
        )

        rows = list(reversed(rows))

        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "id": row.id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "overall_status": row.overall_status,
                    "agents_total": row.agents_total or 0,
                    "agents_online": row.agents_online or 0,
                    "agents_offline": row.agents_offline or 0,
                    "agents_temp_offline": row.agents_temp_offline or 0,
                    "executors_total": row.executors_total or 0,
                    "executors_busy": row.executors_busy or 0,
                    "executors_idle": row.executors_idle or 0,
                    "queue_total": row.queue_total or 0,
                    "queue_buildable": row.queue_buildable or 0,
                    "queue_blocked": row.queue_blocked or 0,
                    "queue_stuck": row.queue_stuck or 0,
                    "executor_usage_percent": self._to_float(row.executor_usage_percent),
                    "avg_cpu_operational_percent": self._to_float(row.avg_cpu_operational_percent),
                    "avg_memory_used_percent": self._to_float(row.avg_memory_used_percent),
                    "min_disk_free_gb": self._to_float(row.min_disk_free_gb),
                    "has_real_cpu_data": self._to_bool(row.has_real_cpu_data),
                    "has_real_memory_data": self._to_bool(row.has_real_memory_data),
                    "has_real_disk_data": self._to_bool(row.has_real_disk_data),
                }
            )

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_capacity",
            "count": len(items),
            "items": items,
        }

    def get_forecast(self, steps: int = 6) -> dict[str, Any]:
        history = self.get_history(limit=20).get("items", [])

        if len(history) < 3:
            return {
                "status": "OK",
                "provider": "JENKINS",
                "method": "linear_trend",
                "message": "Histórico insuficiente para forecast. Gere pelo menos 3 snapshots.",
                "forecast": [],
            }

        queue_total_series = [self._to_float(item.get("queue_total")) for item in history]
        executors_busy_series = [self._to_float(item.get("executors_busy")) for item in history]
        cpu_avg_series = [self._to_float(item.get("avg_cpu_operational_percent")) for item in history]
        memory_avg_series = [self._to_float(item.get("avg_memory_used_percent")) for item in history]
        disk_min_series = [self._to_float(item.get("min_disk_free_gb")) for item in history]

        queue_total_forecast = self._linear_forecast(queue_total_series, steps, floor=0)
        executors_busy_forecast = self._linear_forecast(executors_busy_series, steps, floor=0)
        cpu_avg_forecast = self._linear_forecast(cpu_avg_series, steps, floor=0, cap=100)
        memory_avg_forecast = self._linear_forecast(memory_avg_series, steps, floor=0, cap=100)
        disk_min_forecast = self._linear_forecast(disk_min_series, steps, floor=0)

        items: list[dict[str, Any]] = []
        for index in range(steps):
            items.append(
                {
                    "step": index + 1,
                    "queue_total_pred": queue_total_forecast[index],
                    "executors_busy_pred": executors_busy_forecast[index],
                    "avg_cpu_operational_percent_pred": cpu_avg_forecast[index],
                    "avg_memory_used_percent_pred": memory_avg_forecast[index],
                    "min_disk_free_gb_pred": disk_min_forecast[index],
                }
            )

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_capacity",
            "method": "linear_trend",
            "based_on_snapshots": len(history),
            "forecast": items,
        }

    def get_agents_forecast(self, steps: int = 6) -> dict[str, Any]:
        snapshots = (
            self.db.query(JenkinsCapacitySnapshot)
            .order_by(JenkinsCapacitySnapshot.created_at.asc())
            .limit(50)
            .all()
        )

        if len(snapshots) < 3:
            return {
                "status": "OK",
                "provider": "JENKINS",
                "message": "Histórico insuficiente para forecast por agente. Gere pelo menos 3 snapshots.",
                "agents": [],
            }

        agents_series: dict[str, dict[str, list[float]]] = {}

        for snap in snapshots:
            agents = snap.agents_json or []

            for agent in agents:
                name = agent.get("name")
                if not name:
                    continue

                if name not in agents_series:
                    agents_series[name] = {
                        "cpu": [],
                        "memory": [],
                        "disk": [],
                    }

                agents_series[name]["cpu"].append(self._to_float(agent.get("cpu_operational_percent")))
                agents_series[name]["memory"].append(self._to_float(agent.get("memory_used_percent")))
                agents_series[name]["disk"].append(self._to_float(agent.get("disk_free_gb")))

        result: list[dict[str, Any]] = []

        for name, series in agents_series.items():
            cpu_forecast = self._linear_forecast(series["cpu"], steps, floor=0, cap=100)
            memory_forecast = self._linear_forecast(series["memory"], steps, floor=0, cap=100)
            disk_forecast = self._linear_forecast(series["disk"], steps, floor=0)

            result.append(
                {
                    "agent": name,
                    "forecast": [
                        {
                            "step": i + 1,
                            "cpu": cpu_forecast[i],
                            "memory": memory_forecast[i],
                            "disk": disk_forecast[i],
                        }
                        for i in range(steps)
                    ],
                }
            )

        result = sorted(
            result,
            key=lambda item: min(
                [row.get("disk", 999999) for row in item.get("forecast", [])] or [999999]
            )
        )

        return {
            "status": "OK",
            "provider": "JENKINS",
            "based_on_snapshots": len(snapshots),
            "agents": result,
        }

    def _build_dashboard_from_live_data(self) -> dict[str, Any]:
        result = collect_from_jenkins(self.db)

        if result.get("status") != "OK":
            return {
                "status": "ERROR",
                "provider": "JENKINS",
                "message": result.get("message", "Erro ao coletar dados do Jenkins."),
            }

        summary = result.get("summary", {})
        top_agents = result.get("top_agents", [])
        limitations = result.get("limitations", [])

        return self._build_dashboard_payload(
            summary=summary,
            top_agents=top_agents,
            limitations=limitations,
            snapshot_time=None,
            generated_from="live",
        )

    def _build_dashboard_from_snapshot(self, snapshot: JenkinsCapacitySnapshot) -> dict[str, Any]:
        summary = snapshot.summary_json or {}
        top_agents = snapshot.agents_json or []
        limitations = snapshot.limitations_json or []

        return self._build_dashboard_payload(
            summary=summary,
            top_agents=top_agents,
            limitations=limitations,
            snapshot_time=snapshot.created_at.isoformat() if snapshot.created_at else None,
            generated_from="snapshot",
        )

    def _build_dashboard_payload(
        self,
        summary: dict[str, Any],
        top_agents: list[dict[str, Any]],
        limitations: list[str],
        snapshot_time: str | None,
        generated_from: str,
    ) -> dict[str, Any]:
        avg_cpu_operational_percent = self._avg(
            [item.get("cpu_operational_percent", 0) for item in top_agents]
        )
        avg_memory_used_percent = self._avg(
            [item.get("memory_used_percent", 0) for item in top_agents if item.get("memory_has_real_data")]
        )
        min_disk_free_gb = self._min(
            [item.get("disk_free_gb", 0) for item in top_agents if item.get("disk_has_real_data")]
        )

        cards = {
            "agents_online": f"{summary.get('agents_online', 0)} / {summary.get('agents_total', 0)}",
            "executors_busy": f"{summary.get('executors_busy', 0)} / {summary.get('executors_total', 0)}",
            "cpu_operacional_media": f"{avg_cpu_operational_percent:.2f}%",
            "memoria_media": f"{avg_memory_used_percent:.2f}%",
            "menor_disco_livre": f"{min_disk_free_gb:.2f} GB" if min_disk_free_gb > 0 else "N/D",
            "fila_bloqueada": str(summary.get("queue_blocked", 0)),
        }

        indicators = {
            "overall_status": summary.get("overall_status", "ok"),
            "queue_total": summary.get("queue_total", 0),
            "queue_stuck": summary.get("queue_stuck", 0),
            "has_real_cpu_data": summary.get("has_real_cpu_data", False),
            "has_real_memory_data": summary.get("has_real_memory_data", False),
            "has_real_disk_data": summary.get("has_real_disk_data", False),
        }

        alerts = self._build_alerts(summary, top_agents)

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_capacity",
            "generated_from": generated_from,
            "snapshot_time": snapshot_time,
            "cards": cards,
            "indicators": indicators,
            "alerts": alerts,
            "summary": summary,
            "agents": top_agents,
            "limitations": limitations,
        }

    def _avg(self, values: list[float]) -> float:
        valid = [float(v) for v in values if v is not None]
        if not valid:
            return 0.0
        return round(sum(valid) / len(valid), 2)

    def _min(self, values: list[float]) -> float:
        valid = [float(v) for v in values if v is not None and float(v) > 0]
        if not valid:
            return 0.0
        return round(min(valid), 2)

    def _to_float(self, value: Any) -> float:
        try:
            return round(float(value), 2)
        except Exception:
            return 0.0

    def _to_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"true", "1", "sim", "yes"}

    def _linear_forecast(
        self,
        values: list[float],
        steps: int,
        floor: float | None = None,
        cap: float | None = None,
    ) -> list[float]:
        clean = [float(v or 0) for v in values]
        n = len(clean)

        if n == 0:
            return [0.0 for _ in range(steps)]

        if n == 1:
            base = clean[0]
            return [round(base, 2) for _ in range(steps)]

        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(clean) / n

        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, clean))
        denominator = sum((xi - x_mean) ** 2 for xi in x) or 1

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        result: list[float] = []
        for i in range(n, n + steps):
            pred = intercept + slope * i

            if floor is not None:
                pred = max(pred, floor)

            if cap is not None:
                pred = min(pred, cap)

            result.append(round(pred, 2))

        return result

    def _build_alerts(self, summary: dict[str, Any], agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []

        if summary.get("queue_blocked", 0) > 0:
            alerts.append(
                {
                    "severity": "warning",
                    "title": "Fila bloqueada",
                    "message": f"{summary.get('queue_blocked', 0)} item(ns) bloqueado(s) na fila do Jenkins.",
                }
            )

        if summary.get("queue_stuck", 0) > 0:
            alerts.append(
                {
                    "severity": "critical",
                    "title": "Fila travada",
                    "message": f"{summary.get('queue_stuck', 0)} item(ns) travado(s) na fila do Jenkins.",
                }
            )

        for agent in agents:
            name = agent.get("name", "-")

            if agent.get("offline"):
                alerts.append(
                    {
                        "severity": "critical",
                        "title": f"{name} offline",
                        "message": f"O agent {name} está offline.",
                    }
                )

            if agent.get("temporarily_offline"):
                alerts.append(
                    {
                        "severity": "warning",
                        "title": f"{name} temporariamente offline",
                        "message": f"O agent {name} está temporariamente offline.",
                    }
                )

            if agent.get("memory_has_real_data") and agent.get("memory_used_percent", 0) >= 90:
                severity = "critical" if agent.get("memory_used_percent", 0) >= 95 else "warning"
                alerts.append(
                    {
                        "severity": severity,
                        "title": f"{name} com memória alta",
                        "message": f"Uso de memória em {agent.get('memory_used_percent', 0)}%.",
                    }
                )

            if agent.get("disk_has_real_data") and agent.get("disk_free_gb", 0) <= 10:
                severity = "critical" if agent.get("disk_free_gb", 0) <= 5 else "warning"
                alerts.append(
                    {
                        "severity": severity,
                        "title": f"{name} com pouco disco",
                        "message": f"Disco livre em {agent.get('disk_free_gb', 0)} GB no path {agent.get('disk_path') or '-'}.",
                    }
                )

            if agent.get("cpu_operational_percent", 0) >= 85:
                severity = "critical" if agent.get("cpu_operational_percent", 0) >= 95 else "warning"
                alerts.append(
                    {
                        "severity": severity,
                        "title": f"{name} com CPU operacional alta",
                        "message": f"Ocupação operacional em {agent.get('cpu_operational_percent', 0)}%.",
                    }
                )

        order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(alerts, key=lambda x: order.get(x.get("severity", "info"), 9))[:20]

    def render_dashboard_html(self) -> str:
        return """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Jenkins Capacity Dashboard</title>
  <style>
    :root {
      --bg: #0b0f14;
      --panel: #141a21;
      --panel-2: #1b222c;
      --border: #2a3441;
      --text: #e6edf3;
      --muted: #9fb0c0;
      --green: #299c46;
      --yellow: #e0b400;
      --red: #d44a3a;
      --blue: #3274d9;
      --purple: #8f3bb8;
      --orange: #ff9830;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
    }

    .container {
      max-width: 1700px;
      margin: 0 auto;
      padding: 20px;
    }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      gap: 12px;
      flex-wrap: wrap;
    }

    .title {
      font-size: 28px;
      font-weight: 700;
    }

    .subtitle {
      color: var(--muted);
      font-size: 13px;
      margin-top: 6px;
    }

    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    button {
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 600;
    }

    button:hover {
      background: #222c38;
    }

    .grid-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }

    .card, .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
    }

    .card .label {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 10px;
    }

    .card .value {
      font-size: 28px;
      font-weight: 700;
    }

    .grid-main {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-bottom: 18px;
    }

    .grid-panels {
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
      margin-bottom: 18px;
    }

    .grid-bottom {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-bottom: 18px;
    }

    .grid-agent-forecast {
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
      margin-bottom: 18px;
    }

    h3 {
      margin-top: 0;
      margin-bottom: 14px;
      font-size: 18px;
    }

    .muted {
      color: var(--muted);
    }

    .kv {
      display: grid;
      gap: 10px;
    }

    .kv-row {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      border-bottom: 1px solid rgba(255,255,255,0.05);
      padding-bottom: 8px;
    }

    .status {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }

    .status.ok { background: rgba(41,156,70,0.18); color: #7ee787; }
    .status.warning { background: rgba(224,180,0,0.18); color: #ffd866; }
    .status.critical { background: rgba(212,74,58,0.18); color: #ff7b72; }

    .alert-list {
      display: grid;
      gap: 10px;
    }

    .alert {
      border: 1px solid var(--border);
      border-left: 4px solid var(--blue);
      background: var(--panel-2);
      border-radius: 10px;
      padding: 12px;
    }

    .alert.warning { border-left-color: var(--yellow); }
    .alert.critical { border-left-color: var(--red); }

    .alert-title {
      font-weight: 700;
      margin-bottom: 4px;
    }

    .table-wrap {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 1200px;
    }

    .compact-table {
      min-width: 100%;
    }

    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: middle;
      font-size: 13px;
    }

    th {
      color: var(--muted);
      font-weight: 700;
      position: sticky;
      top: 0;
      background: var(--panel);
    }

    .bar-wrap {
      width: 140px;
      height: 8px;
      background: #0f141b;
      border: 1px solid var(--border);
      border-radius: 999px;
      overflow: hidden;
    }

    .bar {
      height: 100%;
      background: var(--blue);
    }

    .bar.memory { background: var(--orange); }
    .bar.cpu { background: var(--purple); }
    .bar.disk { background: var(--green); }

    .limitations {
      display: grid;
      gap: 8px;
    }

    .limitation {
      color: var(--muted);
      font-size: 13px;
      border-left: 3px solid var(--border);
      padding-left: 10px;
    }

    .snapshot-badge {
      display: inline-block;
      margin-top: 8px;
      padding: 4px 8px;
      border-radius: 999px;
      background: rgba(50,116,217,0.18);
      color: #8ab4f8;
      font-size: 12px;
      font-weight: 700;
    }

    .risk-warning {
      background: rgba(224,180,0,0.12);
    }

    .risk-critical {
      background: rgba(212,74,58,0.16);
    }

    .agent-name {
      font-weight: 700;
      white-space: nowrap;
    }

    @media (max-width: 1100px) {
      .grid-main,
      .grid-panels,
      .grid-bottom,
      .grid-agent-forecast {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <div class="title">Jenkins Capacity Dashboard</div>
        <div class="subtitle">Agents, executors, memória, disco livre e fila do Jenkins</div>
        <div id="snapshotInfo" class="snapshot-badge">Carregando origem dos dados...</div>
      </div>
      <div class="actions">
        <button onclick="collectNow()">Coletar agora</button>
        <button onclick="loadAll()">Atualizar dashboard</button>
      </div>
    </div>

    <div id="cards" class="grid-cards"></div>

    <div class="grid-main">
      <div class="panel">
        <h3>Indicadores</h3>
        <div id="indicators" class="kv"></div>
      </div>
      <div class="panel">
        <h3>Alertas rápidos</h3>
        <div id="alerts" class="alert-list"></div>
      </div>
    </div>

    <div class="grid-panels">
      <div class="panel">
        <h3>Agents</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Agent</th>
                <th>Status</th>
                <th>Executors</th>
                <th>CPU Operacional</th>
                <th>Memória</th>
                <th>Memória Livre</th>
                <th>Disco Livre</th>
                <th>Path</th>
                <th>CPU Real?</th>
                <th>Memória Real?</th>
                <th>Disco Real?</th>
              </tr>
            </thead>
            <tbody id="agentsTable"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="panel">
      <h3>Limitações técnicas</h3>
      <div id="limitations" class="limitations"></div>
    </div>

    <div class="grid-bottom">
      <div class="panel">
        <h3>Histórico recente</h3>
        <div class="table-wrap">
          <table class="compact-table">
            <thead>
              <tr>
                <th>Data</th>
                <th>Agents</th>
                <th>Executors Busy</th>
                <th>Fila</th>
                <th>CPU Média</th>
                <th>Memória Média</th>
                <th>Menor Disco</th>
              </tr>
            </thead>
            <tbody id="historyTable"></tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <h3>Forecast global</h3>
        <div class="table-wrap">
          <table class="compact-table">
            <thead>
              <tr>
                <th>Passo</th>
                <th>Fila Prevista</th>
                <th>Executors Busy Prev.</th>
                <th>CPU Média Prev.</th>
                <th>Memória Média Prev.</th>
                <th>Menor Disco Prev.</th>
              </tr>
            </thead>
            <tbody id="forecastTable"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="grid-agent-forecast">
      <div class="panel">
        <h3>Forecast por agent</h3>
        <div class="table-wrap">
          <table class="compact-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Passo</th>
                <th>CPU Prevista</th>
                <th>Memória Prevista</th>
                <th>Disco Livre Prev.</th>
              </tr>
            </thead>
            <tbody id="agentsForecastTable"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <script>
    function createCard(label, value) {
      return `
        <div class="card">
          <div class="label">${label}</div>
          <div class="value">${value}</div>
        </div>
      `;
    }

    function statusBadge(name) {
      const safe = (name || "ok").toLowerCase();
      return `<span class="status ${safe}">${name || "ok"}</span>`;
    }

    function yesNo(value) {
      return value ? "Sim" : "Não";
    }

    function percentBar(value, cssClass = "") {
      const width = Math.max(0, Math.min(Number(value || 0), 100));
      return `
        <div>
          <div style="margin-bottom:6px;">${width.toFixed(2)}%</div>
          <div class="bar-wrap">
            <div class="bar ${cssClass}" style="width:${width}%;"></div>
          </div>
        </div>
      `;
    }

    function fmtNumber(value, suffix = "") {
      const num = Number(value || 0);
      return `${num.toFixed(2)}${suffix}`;
    }

    function fmtDate(value) {
      if (!value) return "-";
      try {
        return new Date(value).toLocaleString("pt-BR");
      } catch (_) {
        return value;
      }
    }

    function riskClassForDisk(value) {
      const disk = Number(value || 0);
      if (disk <= 5) return "risk-critical";
      if (disk <= 10) return "risk-warning";
      return "";
    }

    function renderSnapshotInfo(dashboard) {
      const target = document.getElementById("snapshotInfo");
      const generatedFrom = dashboard.generated_from || "live";
      const snapshotTime = dashboard.snapshot_time ? fmtDate(dashboard.snapshot_time) : null;

      if (generatedFrom === "snapshot" && snapshotTime) {
        target.innerHTML = `Origem: último snapshot em ${snapshotTime}`;
        return;
      }

      if (generatedFrom === "snapshot") {
        target.innerHTML = `Origem: último snapshot`;
        return;
      }

      target.innerHTML = `Origem: coleta em tempo real`;
    }

    function renderCards(cards) {
      const target = document.getElementById("cards");
      target.innerHTML = [
        createCard("Agents Online", cards.agents_online || "0 / 0"),
        createCard("Executors Busy", cards.executors_busy || "0 / 0"),
        createCard("CPU Operacional Média", cards.cpu_operacional_media || "0%"),
        createCard("Memória Média", cards.memoria_media || "0%"),
        createCard("Menor Disco Livre", cards.menor_disco_livre || "N/D"),
        createCard("Fila Bloqueada", cards.fila_bloqueada || "0"),
      ].join("");
    }

    function renderIndicators(indicators, summary) {
      const target = document.getElementById("indicators");
      target.innerHTML = `
        <div class="kv-row"><span class="muted">Overall status</span><span>${statusBadge(indicators.overall_status || "ok")}</span></div>
        <div class="kv-row"><span class="muted">Queue total</span><span>${summary.queue_total ?? 0}</span></div>
        <div class="kv-row"><span class="muted">Queue blocked</span><span>${summary.queue_blocked ?? 0}</span></div>
        <div class="kv-row"><span class="muted">Queue stuck</span><span>${summary.queue_stuck ?? 0}</span></div>
        <div class="kv-row"><span class="muted">Executors idle</span><span>${summary.executors_idle ?? 0}</span></div>
        <div class="kv-row"><span class="muted">CPU real disponível</span><span>${yesNo(indicators.has_real_cpu_data)}</span></div>
        <div class="kv-row"><span class="muted">Memória real disponível</span><span>${yesNo(indicators.has_real_memory_data)}</span></div>
        <div class="kv-row"><span class="muted">Disco real disponível</span><span>${yesNo(indicators.has_real_disk_data)}</span></div>
      `;
    }

    function renderAlerts(alerts) {
      const target = document.getElementById("alerts");
      if (!alerts || alerts.length === 0) {
        target.innerHTML = `<div class="muted">Sem alertas no momento.</div>`;
        return;
      }

      target.innerHTML = alerts.map(item => `
        <div class="alert ${item.severity || ""}">
          <div class="alert-title">${item.title || ""}</div>
          <div class="muted">${item.message || ""}</div>
        </div>
      `).join("");
    }

    function renderAgents(rows) {
      const target = document.getElementById("agentsTable");
      target.innerHTML = (rows || []).map(row => `
        <tr>
          <td>${row.name ?? ""}</td>
          <td>${statusBadge(row.status || "ok")}</td>
          <td>${row.busy_executors ?? 0} / ${row.total_executors ?? 0}</td>
          <td>${percentBar(row.cpu_operational_percent || 0, 'cpu')}</td>
          <td>${row.memory_has_real_data ? percentBar(row.memory_used_percent || 0, 'memory') : '<span class="muted">N/D</span>'}</td>
          <td>${row.memory_available_gb != null ? `${row.memory_available_gb} GB` : '<span class="muted">N/D</span>'}</td>
          <td>${row.disk_has_real_data ? `${row.disk_free_gb} GB` : '<span class="muted">N/D</span>'}</td>
          <td>${row.disk_path ?? '<span class="muted">N/D</span>'}</td>
          <td>${yesNo(row.cpu_has_real_data)}</td>
          <td>${yesNo(row.memory_has_real_data)}</td>
          <td>${yesNo(row.disk_has_real_data)}</td>
        </tr>
      `).join("");
    }

    function renderLimitations(items) {
      const target = document.getElementById("limitations");
      if (!items || items.length === 0) {
        target.innerHTML = `<div class="muted">Sem limitações reportadas.</div>`;
        return;
      }

      target.innerHTML = items.map(item => `
        <div class="limitation">${item}</div>
      `).join("");
    }

    function renderHistory(items) {
      const target = document.getElementById("historyTable");

      if (!items || items.length === 0) {
        target.innerHTML = `
          <tr>
            <td colspan="7" class="muted">Sem snapshots suficientes no histórico.</td>
          </tr>
        `;
        return;
      }

      target.innerHTML = items.map(item => `
        <tr>
          <td>${fmtDate(item.created_at)}</td>
          <td>${item.agents_online ?? 0} / ${item.agents_total ?? 0}</td>
          <td>${item.executors_busy ?? 0}</td>
          <td>${item.queue_total ?? 0}</td>
          <td>${fmtNumber(item.avg_cpu_operational_percent, '%')}</td>
          <td>${fmtNumber(item.avg_memory_used_percent, '%')}</td>
          <td>${fmtNumber(item.min_disk_free_gb, ' GB')}</td>
        </tr>
      `).join("");
    }

    function renderForecast(payload) {
      const target = document.getElementById("forecastTable");
      const items = payload?.forecast || [];

      if (!items.length) {
        target.innerHTML = `
          <tr>
            <td colspan="6" class="muted">${payload?.message || 'Sem forecast disponível.'}</td>
          </tr>
        `;
        return;
      }

      target.innerHTML = items.map(item => `
        <tr class="${riskClassForDisk(item.min_disk_free_gb_pred)}">
          <td>${item.step ?? '-'}</td>
          <td>${fmtNumber(item.queue_total_pred)}</td>
          <td>${fmtNumber(item.executors_busy_pred)}</td>
          <td>${fmtNumber(item.avg_cpu_operational_percent_pred, '%')}</td>
          <td>${fmtNumber(item.avg_memory_used_percent_pred, '%')}</td>
          <td>${fmtNumber(item.min_disk_free_gb_pred, ' GB')}</td>
        </tr>
      `).join("");
    }

    function renderAgentsForecast(payload) {
      const target = document.getElementById("agentsForecastTable");
      const agents = payload?.agents || [];

      if (!agents.length) {
        target.innerHTML = `
          <tr>
            <td colspan="5" class="muted">${payload?.message || 'Sem forecast por agent disponível.'}</td>
          </tr>
        `;
        return;
      }

      const rows = [];
      for (const agent of agents) {
        const forecastRows = agent.forecast || [];

        if (!forecastRows.length) {
          rows.push(`
            <tr>
              <td class="agent-name">${agent.agent || '-'}</td>
              <td colspan="4" class="muted">Sem dados de forecast.</td>
            </tr>
          `);
          continue;
        }

        forecastRows.forEach((item, index) => {
          rows.push(`
            <tr class="${riskClassForDisk(item.disk)}">
              <td class="agent-name">${index === 0 ? (agent.agent || '-') : ''}</td>
              <td>${item.step ?? '-'}</td>
              <td>${fmtNumber(item.cpu, '%')}</td>
              <td>${fmtNumber(item.memory, '%')}</td>
              <td>${fmtNumber(item.disk, ' GB')}</td>
            </tr>
          `);
        });
      }

      target.innerHTML = rows.join("");
    }

    async function parseJsonResponse(response) {
      if (!response.ok) {
        let errorText = `HTTP ${response.status}`;
        try {
          const errorJson = await response.json();
          errorText = errorJson.detail || errorJson.message || errorText;
        } catch (_) {}
        throw new Error(errorText);
      }
      return await response.json();
    }

    async function loadDashboard() {
      const response = await fetch('/jenkins/capacity/dashboard');
      return await parseJsonResponse(response);
    }

    async function loadHistory() {
      const response = await fetch('/jenkins/capacity/history?limit=10');
      return await parseJsonResponse(response);
    }

    async function loadForecast() {
      const response = await fetch('/jenkins/capacity/forecast?steps=6');
      return await parseJsonResponse(response);
    }

    async function loadAgentsForecast() {
      const response = await fetch('/jenkins/capacity/forecast/agents?steps=6');
      return await parseJsonResponse(response);
    }

    async function collectNow() {
      const response = await fetch('/jenkins/capacity/collect', { method: 'POST' });

      if (!response.ok) {
        let errorText = `HTTP ${response.status}`;
        try {
          const errorJson = await response.json();
          errorText = errorJson.detail || errorJson.message || errorText;
        } catch (_) {}
        alert(`Falha na coleta: ${errorText}`);
        return;
      }

      await loadAll();
      alert('Coleta concluída.');
    }

    async function loadAll() {
      try {
        const [dashboard, history, forecast, agentsForecast] = await Promise.all([
          loadDashboard(),
          loadHistory(),
          loadForecast(),
          loadAgentsForecast(),
        ]);

        if (dashboard.status !== "OK") {
          document.getElementById("cards").innerHTML = `
            <div class="panel">
              <div class="label">Erro</div>
              <div class="value" style="font-size:18px;">${dashboard.message || "Falha ao carregar dashboard do Jenkins."}</div>
            </div>
          `;
          document.getElementById("indicators").innerHTML = "";
          document.getElementById("alerts").innerHTML = "";
          document.getElementById("agentsTable").innerHTML = "";
          document.getElementById("limitations").innerHTML = "";
          document.getElementById("historyTable").innerHTML = "";
          document.getElementById("forecastTable").innerHTML = "";
          document.getElementById("agentsForecastTable").innerHTML = "";
          document.getElementById("snapshotInfo").innerHTML = "Erro ao carregar origem dos dados";
          return;
        }

        renderSnapshotInfo(dashboard);
        renderCards(dashboard.cards || {});
        renderIndicators(dashboard.indicators || {}, dashboard.summary || {});
        renderAlerts(dashboard.alerts || []);
        renderAgents(dashboard.agents || []);
        renderLimitations(dashboard.limitations || []);
        renderHistory(history.items || []);
        renderForecast(forecast || {});
        renderAgentsForecast(agentsForecast || {});
      } catch (error) {
        document.getElementById("cards").innerHTML = `
          <div class="panel">
            <div class="label">Erro</div>
            <div class="value" style="font-size:18px;">${error.message || "Falha ao carregar dashboard do Jenkins."}</div>
          </div>
        `;
        document.getElementById("indicators").innerHTML = "";
        document.getElementById("alerts").innerHTML = "";
        document.getElementById("agentsTable").innerHTML = "";
        document.getElementById("limitations").innerHTML = "";
        document.getElementById("historyTable").innerHTML = `
          <tr><td colspan="7" class="muted">Falha ao carregar histórico.</td></tr>
        `;
        document.getElementById("forecastTable").innerHTML = `
          <tr><td colspan="6" class="muted">Falha ao carregar forecast global.</td></tr>
        `;
        document.getElementById("agentsForecastTable").innerHTML = `
          <tr><td colspan="5" class="muted">Falha ao carregar forecast por agent.</td></tr>
        `;
        document.getElementById("snapshotInfo").innerHTML = "Erro ao carregar origem dos dados";
      }
    }

    loadAll();
  </script>
</body>
</html>
    """