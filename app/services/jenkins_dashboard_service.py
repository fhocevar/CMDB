from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.services.jenkins_capacity_service import collect_from_jenkins


class JenkinsDashboardService:
    def __init__(self, db: Session):
        self.db = db

    def get_dashboard_data(self) -> dict[str, Any]:
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

    h3 {
      margin-top: 0;
      margin-bottom: 14px;
      font-size: 18px;
    }

    .muted {
      color: var(--muted);
    }

    .small {
      font-size: 12px;
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

    .pill {
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      background: rgba(50,116,217,0.18);
      color: #8ab4f8;
      font-size: 12px;
      font-weight: 700;
      margin-right: 6px;
      margin-bottom: 6px;
    }

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

    @media (max-width: 1100px) {
      .grid-main,
      .grid-panels {
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

    async function loadDashboard() {
      const response = await fetch('/jenkins/capacity/dashboard');
      return await response.json();
    }

    async function collectNow() {
      await fetch('/jenkins/capacity/collect', { method: 'POST' });
      await loadAll();
      alert('Coleta concluída.');
    }

    async function loadAll() {
      const dashboard = await loadDashboard();

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
        return;
      }

      renderCards(dashboard.cards || {});
      renderIndicators(dashboard.indicators || {}, dashboard.summary || {});
      renderAlerts(dashboard.alerts || []);
      renderAgents(dashboard.agents || []);
      renderLimitations(dashboard.limitations || []);
    }

    loadAll();
  </script>
</body>
</html>
        """