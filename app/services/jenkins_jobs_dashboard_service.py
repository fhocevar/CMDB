from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.jenkins_jobs_capacity_service import JenkinsJobsCapacityService


class JenkinsJobsDashboardService:
    def __init__(self, db: Session):
        self.db = db
        self.jobs_service = JenkinsJobsCapacityService(db)

    def get_dashboard_data(self) -> dict[str, Any]:
        summary_payload = self.jobs_service.get_jobs_summary(limit=500)
        history_payload = self.jobs_service.get_jobs_history(limit=200)

        jobs = summary_payload.get("jobs", [])
        history_items = history_payload.get("items", [])

        total_jobs = len(jobs)
        jobs_with_failures = sum(1 for job in jobs if (job.get("failures") or 0) > 0)
        jobs_with_details = sum(1 for job in jobs if (job.get("details_collected_count") or 0) > 0)

        avg_duration_values = [
            float(job.get("avg_duration_seconds") or 0)
            for job in jobs
            if job.get("avg_duration_seconds") is not None
        ]
        max_duration_values = [
            float(job.get("max_duration_seconds") or 0)
            for job in jobs
            if job.get("max_duration_seconds") is not None
        ]

        cards = {
            "jobs_monitorados": str(total_jobs),
            "jobs_com_falha": str(jobs_with_failures),
            "jobs_com_detalhe": str(jobs_with_details),
            "duracao_media_jobs": self._format_seconds(self._avg(avg_duration_values)),
            "maior_duracao_job": self._format_seconds(max(max_duration_values) if max_duration_values else 0),
        }

        alerts = []

        for job in jobs[:20]:
            failures = job.get("failures") or 0
            avg_duration = float(job.get("avg_duration_seconds") or 0)
            max_duration = float(job.get("max_duration_seconds") or 0)
            details_count = job.get("details_collected_count") or 0

            if details_count == 0:
                alerts.append(
                    {
                        "severity": "warning",
                        "title": f"{job.get('job_name', '-')}: sem detalhe de build",
                        "message": "A coleta encontrou o job, mas não conseguiu enriquecer os detalhes da última build.",
                    }
                )

            if failures > 0:
                alerts.append(
                    {
                        "severity": "warning" if failures < 3 else "critical",
                        "title": f"{job.get('job_name', '-')}: falhas detectadas",
                        "message": f"{failures} falha(s) encontradas no histórico coletado.",
                    }
                )

            if avg_duration >= 1800:
                alerts.append(
                    {
                        "severity": "warning" if avg_duration < 3600 else "critical",
                        "title": f"{job.get('job_name', '-')}: duração média elevada",
                        "message": f"Duração média de {self._format_seconds(avg_duration)}.",
                    }
                )

            if max_duration >= 3600:
                alerts.append(
                    {
                        "severity": "critical",
                        "title": f"{job.get('job_name', '-')}: pico de duração alto",
                        "message": f"Maior duração observada: {self._format_seconds(max_duration)}.",
                    }
                )

        alerts = alerts[:20]

        top_by_duration = sorted(
            jobs,
            key=lambda x: float(x.get("avg_duration_seconds") or 0),
            reverse=True,
        )[:15]

        recent_history = history_items[:50]

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_job_capacity",
            "cards": cards,
            "alerts": alerts,
            "jobs": jobs,
            "top_by_duration": top_by_duration,
            "history": recent_history,
        }

    def collect_now(self, max_jobs: int = 50) -> dict[str, Any]:
        return self.jobs_service.collect_and_persist_jobs_snapshot(max_jobs=max_jobs)

    def render_dashboard_html(self) -> str:
        return """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Jenkins Jobs Capacity Dashboard</title>
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

    .grid-panels {
      display: grid;
      grid-template-columns: 1fr;
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
      min-width: 1000px;
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

    .status {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }

    .status.success { background: rgba(41,156,70,0.18); color: #7ee787; }
    .status.failure { background: rgba(212,74,58,0.18); color: #ff7b72; }
    .status.unstable { background: rgba(224,180,0,0.18); color: #ffd866; }
    .status.aborted { background: rgba(159,176,192,0.18); color: #c9d1d9; }
    .status.running { background: rgba(50,116,217,0.18); color: #8ab4f8; }
    .status.unknown { background: rgba(143,59,184,0.18); color: #d2a8ff; }

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
        <div class="title">Jenkins Jobs Capacity Dashboard</div>
        <div class="subtitle">Duração, falhas, agent principal e histórico de execuções dos jobs</div>
        <div class="snapshot-badge">Dashboard separado do capacity de agents</div>
      </div>
      <div class="actions">
        <button onclick="collectNow()">Coletar agora</button>
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
        <h3>Top jobs por duração média</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>Duração média</th>
                <th>Maior duração</th>
                <th>Falhas</th>
                <th>Agent principal</th>
              </tr>
            </thead>
            <tbody id="topDurationTable"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="grid-panels">
      <div class="panel">
        <h3>Resumo por job</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>Execuções</th>
                <th>Falhas</th>
                <th>Duração média</th>
                <th>Maior duração</th>
                <th>Agent principal</th>
                <th>Último resultado</th>
                <th>Última build</th>
                <th>Detalhe coletado</th>
              </tr>
            </thead>
            <tbody id="jobsSummaryTable"></tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <h3>Histórico recente</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Data</th>
                <th>Job</th>
                <th>Build</th>
                <th>Resultado</th>
                <th>Status</th>
                <th>Agent</th>
                <th>Duração</th>
                <th>Detalhe</th>
              </tr>
            </thead>
            <tbody id="jobsHistoryTable"></tbody>
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

    function fmtDate(value) {
      if (!value) return "-";
      try {
        return new Date(value).toLocaleString("pt-BR");
      } catch (_) {
        return value;
      }
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

    function resultBadge(result, status) {
      const value = String(result || status || "UNKNOWN").toLowerCase();

      let css = "unknown";
      if (value.includes("success")) css = "success";
      else if (value.includes("failure")) css = "failure";
      else if (value.includes("unstable")) css = "unstable";
      else if (value.includes("aborted")) css = "aborted";
      else if (value.includes("running") || value.includes("building")) css = "running";

      return `<span class="status ${css}">${result || status || "UNKNOWN"}</span>`;
    }

    function boolBadge(value) {
      return value
        ? `<span class="status success">Sim</span>`
        : `<span class="status warning">Não</span>`;
    }

    function riskClass(job) {
      const failures = Number(job.failures || 0);
      const avgDuration = Number(job.avg_duration_seconds || 0);

      if (failures >= 3 || avgDuration >= 3600) return "risk-critical";
      if (failures >= 1 || avgDuration >= 1800) return "risk-warning";
      return "";
    }

    function renderCards(cards) {
      const target = document.getElementById("cards");
      target.innerHTML = [
        createCard("Jobs monitorados", cards.jobs_monitorados || "0"),
        createCard("Jobs com falha", cards.jobs_com_falha || "0"),
        createCard("Jobs com detalhe", cards.jobs_com_detalhe || "0"),
        createCard("Duração média", cards.duracao_media_jobs || "0s"),
        createCard("Maior duração", cards.maior_duracao_job || "0s"),
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

    function renderTopDuration(jobs) {
      const target = document.getElementById("topDurationTable");

      if (!jobs || !jobs.length) {
        target.innerHTML = `<tr><td colspan="5" class="muted">Sem dados.</td></tr>`;
        return;
      }

      target.innerHTML = jobs.map(job => `
        <tr class="${riskClass(job)}">
          <td>${job.job_name || "-"}</td>
          <td>${fmtSeconds(job.avg_duration_seconds)}</td>
          <td>${fmtSeconds(job.max_duration_seconds)}</td>
          <td>${job.failures || 0}</td>
          <td>${job.main_agent || "-"}</td>
        </tr>
      `).join("");
    }

    function renderJobsSummary(jobs) {
      const target = document.getElementById("jobsSummaryTable");

      if (!jobs || !jobs.length) {
        target.innerHTML = `<tr><td colspan="9" class="muted">Sem dados.</td></tr>`;
        return;
      }

      target.innerHTML = jobs.map(job => `
        <tr class="${riskClass(job)}">
          <td>${job.job_name || "-"}</td>
          <td>${job.runs || 0}</td>
          <td>${job.failures || 0}</td>
          <td>${fmtSeconds(job.avg_duration_seconds)}</td>
          <td>${fmtSeconds(job.max_duration_seconds)}</td>
          <td>${job.main_agent || "-"}</td>
          <td>${job.last_result ? resultBadge(job.last_result, null) : '<span class="muted">Sem detalhe</span>'}</td>
          <td>${job.last_build_number ?? "-"}</td>
          <td>${boolBadge((job.details_collected_count || 0) > 0)}</td>
        </tr>
      `).join("");
    }

    function renderJobsHistory(items) {
      const target = document.getElementById("jobsHistoryTable");

      if (!items || !items.length) {
        target.innerHTML = `<tr><td colspan="8" class="muted">Sem histórico.</td></tr>`;
        return;
      }

      target.innerHTML = items.map(item => `
        <tr>
          <td>${fmtDate(item.created_at)}</td>
          <td>${item.job_name || "-"}</td>
          <td>${item.build_number ?? "-"}</td>
          <td>${item.result ? resultBadge(item.result, null) : '<span class="muted">Sem detalhe</span>'}</td>
          <td>${item.status ? resultBadge(null, item.status) : '<span class="muted">-</span>'}</td>
          <td>${item.built_on || "-"}</td>
          <td>${fmtSeconds(item.duration_seconds)}</td>
          <td>${boolBadge(item.details_collected)}</td>
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
      const response = await fetch('/jenkins/jobs/dashboard');
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
              <div class="value" style="font-size:18px;">${dashboard.message || "Falha ao carregar dashboard de jobs."}</div>
            </div>
          `;
          document.getElementById("alerts").innerHTML = "";
          document.getElementById("topDurationTable").innerHTML = "";
          document.getElementById("jobsSummaryTable").innerHTML = "";
          document.getElementById("jobsHistoryTable").innerHTML = "";
          return;
        }

        renderCards(dashboard.cards || {});
        renderAlerts(dashboard.alerts || []);
        renderTopDuration(dashboard.top_by_duration || []);
        renderJobsSummary(dashboard.jobs || []);
        renderJobsHistory(dashboard.history || []);
      } catch (error) {
        document.getElementById("cards").innerHTML = `
          <div class="panel">
            <div class="label">Erro</div>
            <div class="value" style="font-size:18px;">${error.message || "Falha ao carregar dashboard de jobs."}</div>
          </div>
        `;
        document.getElementById("alerts").innerHTML = "";
        document.getElementById("topDurationTable").innerHTML = "";
        document.getElementById("jobsSummaryTable").innerHTML = "";
        document.getElementById("jobsHistoryTable").innerHTML = "";
      }
    }

    loadAll();
  </script>
</body>
</html>
        """

    def _avg(self, values: list[float]) -> float:
        valid = [float(v) for v in values if v is not None]
        if not valid:
            return 0.0
        return round(sum(valid) / len(valid), 2)

    def _format_seconds(self, seconds: float | int | None) -> str:
        total = int(float(seconds or 0))

        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60

        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        if minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"