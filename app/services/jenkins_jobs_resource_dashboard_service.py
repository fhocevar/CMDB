from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.jenkins_jobs_resource_profile_service import JenkinsJobsResourceProfileService


class JenkinsJobsResourceDashboardService:
    def __init__(self, db: Session):
        self.db = db
        self.resource_service = JenkinsJobsResourceProfileService(db)

    def get_dashboard_data(self) -> dict[str, Any]:
        payload = self.resource_service.get_jobs_resource_profiles(limit=100, padding_minutes=10)
        items = payload.get("items", [])

        correlated = [item for item in items if item.get("correlated")]
        critical = [item for item in correlated if item.get("risk_level") == "critical"]
        warning = [item for item in correlated if item.get("risk_level") == "warning"]

        min_disk_values = [
            item.get("min_disk_free_gb_during_job")
            for item in correlated
            if item.get("min_disk_free_gb_during_job") is not None
        ]
        avg_memory_values = [
            item.get("avg_memory_used_percent_during_job")
            for item in correlated
            if item.get("avg_memory_used_percent_during_job") is not None
        ]

        cards = {
            "jobs_analisados": str(len(items)),
            "jobs_correlacionados": str(len(correlated)),
            "jobs_criticos": str(len(critical)),
            "jobs_warning": str(len(warning)),
            "menor_disco_observado": f"{min(min_disk_values):.2f} GB" if min_disk_values else "N/D",
            "memoria_media_jobs": f"{(sum(avg_memory_values) / len(avg_memory_values)):.2f}%" if avg_memory_values else "N/D",
        }

        top_risk = sorted(
            correlated,
            key=lambda item: (
                0 if item.get("risk_level") == "critical" else 1 if item.get("risk_level") == "warning" else 2,
                item.get("min_disk_free_gb_during_job") if item.get("min_disk_free_gb_during_job") is not None else 999999,
            ),
        )[:20]

        alerts: list[dict[str, Any]] = []
        for item in top_risk[:10]:
            reasons = item.get("risk_reasons") or []
            if reasons:
                alerts.append(
                    {
                        "severity": item.get("risk_level", "warning"),
                        "title": f"{item.get('job_name', '-')} #{item.get('build_number') or '-'}",
                        "message": " | ".join(reasons),
                    }
                )

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_job_resource_profile",
            "cards": cards,
            "alerts": alerts,
            "items": items,
            "top_risk": top_risk,
        }

    def render_dashboard_html(self) -> str:
        return """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Jenkins Jobs Resource Dashboard</title>
  <style>
    :root {
      --bg: #0b0f14;
      --panel: #141a21;
      --panel-2: #1b222c;
      --border: #2a3441;
      --text: #e6edf3;
      --muted: #9fb0c0;
      --yellow: #e0b400;
      --red: #d44a3a;
      --blue: #3274d9;
      --green: #299c46;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
    }

    .container {
      max-width: 1800px;
      margin: 0 auto;
      padding: 20px;
    }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 20px;
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
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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
    .alert.ok { border-left-color: var(--green); }

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
      background: var(--panel);
      position: sticky;
      top: 0;
    }

    .muted {
      color: var(--muted);
    }

    .risk-warning {
      background: rgba(224,180,0,0.12);
    }

    .risk-critical {
      background: rgba(212,74,58,0.16);
    }

    .risk-ok {
      background: rgba(41,156,70,0.08);
    }

    .badge {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }

    .badge-ok { background: rgba(41,156,70,0.18); color: #7ee787; }
    .badge-warning { background: rgba(224,180,0,0.18); color: #ffd866; }
    .badge-critical { background: rgba(212,74,58,0.18); color: #ff7b72; }
    .badge-unknown { background: rgba(50,116,217,0.18); color: #8ab4f8; }

    @media (max-width: 1100px) {
      .grid-main {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <div class="title">Jenkins Jobs Resource Dashboard</div>
        <div class="subtitle">Correlação entre execução dos jobs e consumo observado nos agents</div>
      </div>
      <div class="actions">
        <button onclick="collectNow()">Coletar jobs agora</button>
        <button onclick="loadAll()">Atualizar dashboard</button>
      </div>
    </div>

    <div id="cards" class="grid-cards"></div>

    <div class="grid-main">
      <div class="panel">
        <h3>Alertas rápidos</h3>
        <div id="alerts" class="alert-list"></div>
      </div>

      <div class="panel">
        <h3>Top jobs por risco</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>Build</th>
                <th>Agent</th>
                <th>CPU média</th>
                <th>Memória média</th>
                <th>Menor disco</th>
                <th>Delta disco</th>
                <th>Risco</th>
              </tr>
            </thead>
            <tbody id="topRiskTable"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="panel">
      <h3>Perfis de recurso por job</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Data</th>
              <th>Job</th>
              <th>Build</th>
              <th>Agent</th>
              <th>Duração</th>
              <th>Snapshots</th>
              <th>CPU média</th>
              <th>Memória média</th>
              <th>Menor disco</th>
              <th>Delta disco</th>
              <th>Risco</th>
              <th>Mensagem</th>
            </tr>
          </thead>
          <tbody id="profilesTable"></tbody>
        </table>
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

    function fmtDate(value) {
      if (!value) return "-";
      try {
        return new Date(value).toLocaleString("pt-BR");
      } catch (_) {
        return value;
      }
    }

    function fmtNumber(value, suffix = "") {
      if (value === null || value === undefined) return "N/D";
      return `${Number(value).toFixed(2)}${suffix}`;
    }

    function fmtSeconds(seconds) {
      const total = Number(seconds || 0);
      if (!total) return "0s";
      const h = Math.floor(total / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = Math.floor(total % 60);
      if (h > 0) return `${h}h ${m}m ${s}s`;
      if (m > 0) return `${m}m ${s}s`;
      return `${s}s`;
    }

    function riskBadge(level) {
      const value = String(level || "unknown").toLowerCase();
      const css =
        value === "critical" ? "badge-critical" :
        value === "warning" ? "badge-warning" :
        value === "ok" ? "badge-ok" : "badge-unknown";

      return `<span class="badge ${css}">${level || "unknown"}</span>`;
    }

    function rowClass(level) {
      const value = String(level || "unknown").toLowerCase();
      if (value === "critical") return "risk-critical";
      if (value === "warning") return "risk-warning";
      if (value === "ok") return "risk-ok";
      return "";
    }

    function renderCards(cards) {
      const target = document.getElementById("cards");
      target.innerHTML = [
        createCard("Jobs analisados", cards.jobs_analisados || "0"),
        createCard("Jobs correlacionados", cards.jobs_correlacionados || "0"),
        createCard("Jobs críticos", cards.jobs_criticos || "0"),
        createCard("Jobs warning", cards.jobs_warning || "0"),
        createCard("Menor disco observado", cards.menor_disco_observado || "N/D"),
        createCard("Memória média jobs", cards.memoria_media_jobs || "N/D"),
      ].join("");
    }

    function renderAlerts(alerts) {
      const target = document.getElementById("alerts");
      if (!alerts || !alerts.length) {
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

    function renderTopRisk(items) {
      const target = document.getElementById("topRiskTable");
      if (!items || !items.length) {
        target.innerHTML = `<tr><td colspan="8" class="muted">Sem dados.</td></tr>`;
        return;
      }

      target.innerHTML = items.map(item => `
        <tr class="${rowClass(item.risk_level)}">
          <td>${item.job_name || "-"}</td>
          <td>${item.build_number ?? "-"}</td>
          <td>${item.built_on || "-"}</td>
          <td>${fmtNumber(item.avg_cpu_operational_percent_during_job, "%")}</td>
          <td>${fmtNumber(item.avg_memory_used_percent_during_job, "%")}</td>
          <td>${fmtNumber(item.min_disk_free_gb_during_job, " GB")}</td>
          <td>${fmtNumber(item.disk_free_delta_gb_during_job, " GB")}</td>
          <td>${riskBadge(item.risk_level)}</td>
        </tr>
      `).join("");
    }

    function renderProfiles(items) {
      const target = document.getElementById("profilesTable");
      if (!items || !items.length) {
        target.innerHTML = `<tr><td colspan="12" class="muted">Sem dados.</td></tr>`;
        return;
      }

      target.innerHTML = items.map(item => `
        <tr class="${rowClass(item.risk_level)}">
          <td>${fmtDate(item.created_at)}</td>
          <td>${item.job_name || "-"}</td>
          <td>${item.build_number ?? "-"}</td>
          <td>${item.built_on || "-"}</td>
          <td>${fmtSeconds(item.duration_seconds)}</td>
          <td>${item.matching_snapshots ?? 0}</td>
          <td>${fmtNumber(item.avg_cpu_operational_percent_during_job, "%")}</td>
          <td>${fmtNumber(item.avg_memory_used_percent_during_job, "%")}</td>
          <td>${fmtNumber(item.min_disk_free_gb_during_job, " GB")}</td>
          <td>${fmtNumber(item.disk_free_delta_gb_during_job, " GB")}</td>
          <td>${riskBadge(item.risk_level)}</td>
          <td>${item.message || "-"}</td>
        </tr>
      `).join("");
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
      const response = await fetch('/jenkins/jobs/resources/dashboard');
      return await parseJsonResponse(response);
    }

    async function collectNow() {
      const response = await fetch('/jenkins/jobs/collect?max_jobs=50', { method: 'POST' });

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
        const dashboard = await loadDashboard();

        if (dashboard.status !== "OK") {
          document.getElementById("cards").innerHTML = `
            <div class="panel">
              <div class="label">Erro</div>
              <div class="value" style="font-size:18px;">${dashboard.message || "Falha ao carregar dashboard de recursos."}</div>
            </div>
          `;
          document.getElementById("alerts").innerHTML = "";
          document.getElementById("topRiskTable").innerHTML = "";
          document.getElementById("profilesTable").innerHTML = "";
          return;
        }

        renderCards(dashboard.cards || {});
        renderAlerts(dashboard.alerts || []);
        renderTopRisk(dashboard.top_risk || []);
        renderProfiles(dashboard.items || []);
      } catch (error) {
        document.getElementById("cards").innerHTML = `
          <div class="panel">
            <div class="label">Erro</div>
            <div class="value" style="font-size:18px;">${error.message || "Falha ao carregar dashboard de recursos."}</div>
          </div>
        `;
        document.getElementById("alerts").innerHTML = "";
        document.getElementById("topRiskTable").innerHTML = "";
        document.getElementById("profilesTable").innerHTML = "";
      }
    }

    loadAll();
  </script>
</body>
</html>
        """