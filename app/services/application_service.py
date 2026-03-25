from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.integrations.argocd_client import ArgoCDClient
from app.models.app_capacity_snapshot import AppCapacitySnapshot


class ApplicationService:
    def __init__(self, db: Session):
        self.db = db
        self.client = ArgoCDClient()
        self._logged_in = False

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.client.login()
            self._logged_in = True

    def _safe_get(self, data: dict, *keys, default=None):
        current = data
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key)
            if current is None:
                return default
        return current

    def _parse_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            if value.endswith("Z"):
                value = value.replace("Z", "+00:00")
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _duration_seconds(self, started_at: str | None, finished_at: str | None) -> float | None:
        start = self._parse_dt(started_at)
        end = self._parse_dt(finished_at)
        if not start or not end:
            return None
        return round((end - start).total_seconds(), 2)

    def _extract_sync_policy(self, spec: dict) -> dict:
        sync_policy = spec.get("syncPolicy", {}) or {}
        automated = sync_policy.get("automated", {}) or {}
        retry = sync_policy.get("retry", {}) or {}
        sync_options = sync_policy.get("syncOptions", []) or []

        return {
            "automated_enabled": bool(automated),
            "prune_enabled": bool(automated.get("prune", False)),
            "self_heal_enabled": bool(automated.get("selfHeal", False)),
            "allow_empty_enabled": bool(automated.get("allowEmpty", False)),
            "retry_enabled": bool(retry),
            "sync_options": sync_options,
        }

    def _detect_source_type(self, spec: dict) -> str:
        source = spec.get("source", {}) or {}
        sources = spec.get("sources", []) or []

        inspect_sources = [source] if source else []
        inspect_sources.extend([item for item in sources if isinstance(item, dict)])

        for src in inspect_sources:
            if src.get("helm") is not None or src.get("chart"):
                return "HELM"
            if src.get("kustomize") is not None:
                return "KUSTOMIZE"
            if src.get("directory") is not None:
                return "DIRECTORY"
            if src.get("plugin") is not None:
                return "PLUGIN"

        return "GIT"

    def _extract_revisions(self, status: dict) -> dict:
        sync = status.get("sync", {}) or {}
        operation_state = status.get("operationState", {}) or {}
        sync_result = operation_state.get("syncResult", {}) or {}

        return {
            "sync_revision": sync.get("revision"),
            "operation_revision": sync_result.get("revision"),
        }

    def _extract_operation_state(self, status: dict) -> dict:
        operation_state = status.get("operationState", {}) or {}
        started_at = operation_state.get("startedAt")
        finished_at = operation_state.get("finishedAt")

        return {
            "phase": operation_state.get("phase"),
            "message": operation_state.get("message"),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": self._duration_seconds(started_at, finished_at),
        }

    def _extract_resources(self, status: dict) -> dict:
        resources = status.get("resources", []) or []

        resource_items: list[dict[str, Any]] = []
        resource_kinds = Counter()

        degraded_resources = 0
        missing_resources = 0
        out_of_sync_resources = 0
        unknown_resources = 0

        for item in resources:
            kind = item.get("kind")
            namespace = item.get("namespace")
            name = item.get("name")
            version = item.get("version")
            group = item.get("group")
            status_value = item.get("status")
            health = item.get("health", {}) if isinstance(item.get("health"), dict) else {}
            health_status = health.get("status")

            if kind:
                resource_kinds[kind] += 1

            if status_value == "OutOfSync":
                out_of_sync_resources += 1

            if health_status == "Degraded":
                degraded_resources += 1
            elif health_status == "Missing":
                missing_resources += 1
            elif health_status in (None, "Unknown"):
                unknown_resources += 1

            resource_items.append(
                {
                    "kind": kind,
                    "group": group,
                    "version": version,
                    "namespace": namespace,
                    "name": name,
                    "sync_status": status_value,
                    "health_status": health_status,
                }
            )

        return {
            "resources_total": len(resources),
            "resource_kinds": dict(resource_kinds),
            "resources_degraded": degraded_resources,
            "resources_missing": missing_resources,
            "resources_out_of_sync": out_of_sync_resources,
            "resources_unknown": unknown_resources,
            "resources": resource_items,
        }

    def _extract_conditions(self, status: dict) -> list[dict]:
        conditions = status.get("conditions", []) or []
        return [{"type": item.get("type"), "message": item.get("message")} for item in conditions]

    def _extract_summary(self, status: dict) -> dict:
        summary = status.get("summary", {}) or {}
        images = summary.get("images", []) or []
        external_urls = summary.get("externalURLs", []) or []

        return {
            "images": images,
            "images_count": len(images),
            "external_urls": external_urls,
            "external_urls_count": len(external_urls),
        }

    def _extract_source_details(self, spec: dict) -> dict:
        source = spec.get("source", {}) or {}
        sources = spec.get("sources", []) or []

        return {
            "repo_url": source.get("repoURL"),
            "target_revision": source.get("targetRevision"),
            "path": source.get("path"),
            "chart": source.get("chart"),
            "sources_count": len(sources),
            "has_multiple_sources": len(sources) > 1,
        }

    def _extract_destination_details(self, spec: dict) -> dict:
        destination = spec.get("destination", {}) or {}
        return {
            "server": destination.get("server"),
            "name": destination.get("name"),
            "namespace": destination.get("namespace"),
        }

    def _score_application(self, app_result: dict) -> dict:
        score = 100.0
        reasons: list[str] = []

        sync_status = (app_result.get("sync_status") or "Unknown").strip().lower()
        health_status = (app_result.get("health_status") or "Unknown").strip().lower()
        operation_phase = (app_result.get("operation_phase") or "Unknown").strip().lower()

        resources_degraded = int(app_result.get("resources_degraded") or 0)
        resources_missing = int(app_result.get("resources_missing") or 0)
        resources_out_of_sync = int(app_result.get("resources_out_of_sync") or 0)
        conditions_count = int(app_result.get("conditions_count") or 0)
        automated_enabled = bool(app_result.get("automated_enabled"))
        self_heal_enabled = bool(app_result.get("self_heal_enabled"))
        prune_enabled = bool(app_result.get("prune_enabled"))
        operation_duration_seconds = app_result.get("operation_duration_seconds") or 0

        if health_status == "degraded":
            score -= 45
            reasons.append("Application Degraded")
        elif health_status == "missing":
            score -= 55
            reasons.append("Application Missing")
        elif health_status == "progressing":
            score -= 20
            reasons.append("Application Progressing")
        elif health_status == "suspended":
            score -= 25
            reasons.append("Application Suspended")
        elif health_status == "unknown":
            score -= 15
            reasons.append("Health status Unknown")

        if sync_status == "outofsync":
            score -= 25
            reasons.append("Application OutOfSync")
        elif sync_status == "unknown":
            score -= 10
            reasons.append("Sync status Unknown")

        if operation_phase == "failed":
            score -= 30
            reasons.append("Last operation Failed")
        elif operation_phase in {"error", "errored"}:
            score -= 35
            reasons.append("Last operation Errored")
        elif operation_phase == "running":
            score -= 10
            reasons.append("Operation Running")

        if resources_degraded > 0:
            penalty = min(resources_degraded * 10, 25)
            score -= penalty
            reasons.append(f"Resources Degraded: {resources_degraded}")

        if resources_missing > 0:
            penalty = min(resources_missing * 12, 24)
            score -= penalty
            reasons.append(f"Resources Missing: {resources_missing}")

        if resources_out_of_sync > 0:
            penalty = min(resources_out_of_sync * 6, 18)
            score -= penalty
            reasons.append(f"Resources OutOfSync: {resources_out_of_sync}")

        if conditions_count > 0:
            penalty = min(conditions_count * 5, 15)
            score -= penalty
            reasons.append(f"Conditions detected: {conditions_count}")

        if not automated_enabled:
            score -= 5
            reasons.append("Auto-sync disabled")

        if not self_heal_enabled:
            score -= 5
            reasons.append("Self-heal disabled")

        if not prune_enabled:
            score -= 3
            reasons.append("Prune disabled")

        if operation_duration_seconds and operation_duration_seconds >= 30:
            score -= 5
            reasons.append(f"Slow operation: {operation_duration_seconds}s")

        score = max(0.0, min(100.0, round(score, 2)))

        if score >= 90:
            capacity_status = "SAUDAVEL"
        elif score >= 70:
            capacity_status = "ATENCAO"
        elif score >= 40:
            capacity_status = "CRITICO"
        else:
            capacity_status = "SATURADO"

        return {
            "capacity_score": score,
            "capacity_status": capacity_status,
            "reasons": reasons,
        }

    def _build_application_result(self, app: dict) -> dict:
        metadata = app.get("metadata", {}) or {}
        spec = app.get("spec", {}) or {}
        status = app.get("status", {}) or {}

        app_name = metadata.get("name")
        project = spec.get("project")
        sync_status = self._safe_get(status, "sync", "status")
        health_status = self._safe_get(status, "health", "status")

        source_details = self._extract_source_details(spec)
        destination_details = self._extract_destination_details(spec)
        sync_policy = self._extract_sync_policy(spec)
        revisions = self._extract_revisions(status)
        operation_state = self._extract_operation_state(status)
        resources_info = self._extract_resources(status)
        conditions = self._extract_conditions(status)
        summary = self._extract_summary(status)

        result = {
            "application": app_name,
            "project": project,
            "namespace": destination_details["namespace"],
            "destination_server": destination_details["server"],
            "destination_name": destination_details["name"],
            "repo": source_details["repo_url"],
            "revision": source_details["target_revision"],
            "path": source_details["path"],
            "chart": source_details["chart"],
            "source_type": self._detect_source_type(spec),
            "has_multiple_sources": source_details["has_multiple_sources"],
            "sources_count": source_details["sources_count"],
            "sync_status": sync_status,
            "health_status": health_status,
            "sync_revision": revisions["sync_revision"],
            "operation_revision": revisions["operation_revision"],
            "operation_phase": operation_state["phase"],
            "operation_message": operation_state["message"],
            "operation_started_at": operation_state["started_at"],
            "operation_finished_at": operation_state["finished_at"],
            "operation_duration_seconds": operation_state["duration_seconds"],
            "automated_enabled": sync_policy["automated_enabled"],
            "prune_enabled": sync_policy["prune_enabled"],
            "self_heal_enabled": sync_policy["self_heal_enabled"],
            "allow_empty_enabled": sync_policy["allow_empty_enabled"],
            "retry_enabled": sync_policy["retry_enabled"],
            "sync_options": sync_policy["sync_options"],
            "resources_total": resources_info["resources_total"],
            "resource_kinds": resources_info["resource_kinds"],
            "resources_degraded": resources_info["resources_degraded"],
            "resources_missing": resources_info["resources_missing"],
            "resources_out_of_sync": resources_info["resources_out_of_sync"],
            "resources_unknown": resources_info["resources_unknown"],
            "resources": resources_info["resources"],
            "conditions": conditions,
            "conditions_count": len(conditions),
            "images": summary["images"],
            "images_count": summary["images_count"],
            "external_urls": summary["external_urls"],
            "external_urls_count": summary["external_urls_count"],
        }

        score_result = self._score_application(result)
        result["capacity_score"] = score_result["capacity_score"]
        result["capacity_status"] = score_result["capacity_status"]
        result["reasons"] = score_result["reasons"]

        return result

    def _save_snapshot(self, run_id: str, app_result: dict) -> AppCapacitySnapshot:
        snapshot = AppCapacitySnapshot(
            run_id=run_id,
            collected_at=datetime.utcnow(),
            application=app_result["application"],
            project=app_result.get("project"),
            namespace=app_result.get("namespace"),
            destination_server=app_result.get("destination_server"),
            destination_name=app_result.get("destination_name"),
            repo=app_result.get("repo"),
            revision=app_result.get("revision"),
            path=app_result.get("path"),
            chart=app_result.get("chart"),
            source_type=app_result.get("source_type"),
            has_multiple_sources=bool(app_result.get("has_multiple_sources", False)),
            sources_count=int(app_result.get("sources_count") or 0),
            sync_status=app_result.get("sync_status"),
            health_status=app_result.get("health_status"),
            sync_revision=app_result.get("sync_revision"),
            operation_revision=app_result.get("operation_revision"),
            operation_phase=app_result.get("operation_phase"),
            operation_message=app_result.get("operation_message"),
            operation_started_at=self._parse_dt(app_result.get("operation_started_at")),
            operation_finished_at=self._parse_dt(app_result.get("operation_finished_at")),
            operation_duration_seconds=app_result.get("operation_duration_seconds"),
            automated_enabled=bool(app_result.get("automated_enabled", False)),
            prune_enabled=bool(app_result.get("prune_enabled", False)),
            self_heal_enabled=bool(app_result.get("self_heal_enabled", False)),
            allow_empty_enabled=bool(app_result.get("allow_empty_enabled", False)),
            retry_enabled=bool(app_result.get("retry_enabled", False)),
            sync_options=app_result.get("sync_options"),
            resources_total=int(app_result.get("resources_total") or 0),
            resource_kinds=app_result.get("resource_kinds"),
            resources_degraded=int(app_result.get("resources_degraded") or 0),
            resources_missing=int(app_result.get("resources_missing") or 0),
            resources_out_of_sync=int(app_result.get("resources_out_of_sync") or 0),
            resources_unknown=int(app_result.get("resources_unknown") or 0),
            resources=app_result.get("resources"),
            conditions=app_result.get("conditions"),
            conditions_count=int(app_result.get("conditions_count") or 0),
            images=app_result.get("images"),
            images_count=int(app_result.get("images_count") or 0),
            external_urls=app_result.get("external_urls"),
            external_urls_count=int(app_result.get("external_urls_count") or 0),
            capacity_score=float(app_result.get("capacity_score") or 0),
            capacity_status=app_result.get("capacity_status") or "ATENCAO",
            reasons=app_result.get("reasons"),
        )
        self.db.add(snapshot)
        return snapshot

    def collect_and_persist(self) -> dict:
        self._ensure_login()
        apps = self.client.list_applications()

        run_id = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]
        results = []

        for app in apps:
            name = app.get("metadata", {}).get("name")
            if not name:
                continue

            result = self._build_application_result(app)
            results.append(result)
            self._save_snapshot(run_id, result)

        self.db.commit()

        by_status = Counter(item["capacity_status"] for item in results)

        return {
            "status": "OK",
            "run_id": run_id,
            "applications_collected": len(results),
            "by_capacity_status": dict(by_status),
        }

    def get_application_capacity(self, app_name: str):
        self._ensure_login()
        app = self.client.get_application(app_name)
        return self._build_application_result(app)

    def list_capacity_live(self):
        self._ensure_login()
        apps = self.client.list_applications()

        results = []
        for app in apps:
            name = app.get("metadata", {}).get("name")
            if not name:
                continue
            results.append(self._build_application_result(app))

        return results

    def _latest_run_id(self) -> str | None:
        return self.db.query(func.max(AppCapacitySnapshot.run_id)).scalar()

    def get_latest_snapshots(self) -> list[AppCapacitySnapshot]:
        run_id = self._latest_run_id()
        if not run_id:
            return []

        return (
            self.db.query(AppCapacitySnapshot)
            .filter(AppCapacitySnapshot.run_id == run_id)
            .order_by(AppCapacitySnapshot.capacity_score.asc(), AppCapacitySnapshot.application.asc())
            .all()
        )

    def get_grafana_dashboard(self) -> dict:
        snapshots = self.get_latest_snapshots()
        if not snapshots:
            return {
                "cards": {},
                "gauges": {},
                "bars": {},
                "tables": {},
            }

        total = len(snapshots)
        healthy = sum(1 for x in snapshots if x.capacity_status == "SAUDAVEL")
        warning = sum(1 for x in snapshots if x.capacity_status == "ATENCAO")
        critical = sum(1 for x in snapshots if x.capacity_status == "CRITICO")
        saturated = sum(1 for x in snapshots if x.capacity_status == "SATURADO")

        avg_score = round(sum(x.capacity_score for x in snapshots) / total, 2)
        auto_sync_enabled = sum(1 for x in snapshots if x.automated_enabled)
        self_heal_enabled = sum(1 for x in snapshots if x.self_heal_enabled)
        out_of_sync = sum(1 for x in snapshots if (x.sync_status or "") == "OutOfSync")
        degraded = sum(1 for x in snapshots if (x.health_status or "") == "Degraded")
        failed_ops = sum(1 for x in snapshots if (x.operation_phase or "") == "Failed")

        by_project = Counter((x.project or "UNKNOWN") for x in snapshots)
        by_namespace = Counter((x.namespace or "UNKNOWN") for x in snapshots)
        by_cluster = Counter((x.destination_name or x.destination_server or "UNKNOWN") for x in snapshots)
        by_sync_status = Counter((x.sync_status or "Unknown") for x in snapshots)
        by_health_status = Counter((x.health_status or "Unknown") for x in snapshots)
        resource_kinds_total = Counter()

        for item in snapshots:
            if item.resource_kinds:
                for kind, qty in item.resource_kinds.items():
                    resource_kinds_total[kind] += int(qty)

        top_risky = [
            {
                "application": x.application,
                "project": x.project,
                "namespace": x.namespace,
                "capacity_score": x.capacity_score,
                "capacity_status": x.capacity_status,
                "sync_status": x.sync_status,
                "health_status": x.health_status,
                "operation_phase": x.operation_phase,
                "reasons": x.reasons or [],
            }
            for x in sorted(snapshots, key=lambda s: (s.capacity_score, s.application))[:15]
        ]

        failed_operations = [
            {
                "application": x.application,
                "operation_phase": x.operation_phase,
                "operation_duration_seconds": x.operation_duration_seconds,
                "operation_message": x.operation_message,
            }
            for x in snapshots
            if (x.operation_phase or "").lower() in {"failed", "error", "errored"}
        ]

        slow_operations = [
            {
                "application": x.application,
                "operation_duration_seconds": x.operation_duration_seconds,
                "operation_phase": x.operation_phase,
            }
            for x in sorted(
                [s for s in snapshots if s.operation_duration_seconds is not None],
                key=lambda s: s.operation_duration_seconds or 0,
                reverse=True,
            )[:15]
        ]

        return {
            "cards": {
                "applications_total": total,
                "capacity_score_avg": avg_score,
                "healthy_total": healthy,
                "warning_total": warning,
                "critical_total": critical,
                "saturated_total": saturated,
                "out_of_sync_total": out_of_sync,
                "degraded_total": degraded,
                "failed_operations_total": failed_ops,
            },
            "gauges": {
                "auto_sync_enabled_percent": round((auto_sync_enabled / total) * 100, 2),
                "self_heal_enabled_percent": round((self_heal_enabled / total) * 100, 2),
                "healthy_percent": round((healthy / total) * 100, 2),
                "critical_percent": round(((critical + saturated) / total) * 100, 2),
            },
            "bars": {
                "by_capacity_status": {
                    "SAUDAVEL": healthy,
                    "ATENCAO": warning,
                    "CRITICO": critical,
                    "SATURADO": saturated,
                },
                "by_sync_status": dict(by_sync_status),
                "by_health_status": dict(by_health_status),
                "top_projects": dict(by_project.most_common(15)),
                "top_namespaces": dict(by_namespace.most_common(15)),
                "top_clusters": dict(by_cluster.most_common(15)),
                "resource_kinds_total": dict(resource_kinds_total),
            },
            "tables": {
                "top_risky_applications": top_risky,
                "failed_operations": failed_operations,
                "slow_operations": slow_operations,
            },
        }

    def get_capacity_history(self, days: int = 30) -> dict:
        since = datetime.utcnow() - timedelta(days=days)

        rows = (
            self.db.query(
        AppCapacitySnapshot.run_id,
        func.min(AppCapacitySnapshot.collected_at).label("collected_at"),
        func.count(AppCapacitySnapshot.id).label("applications_total"),
        func.avg(AppCapacitySnapshot.capacity_score).label("avg_score"),
        func.sum(
            case((AppCapacitySnapshot.capacity_status == "SAUDAVEL", 1), else_=0)
        ).label("healthy_total"),
        func.sum(
            case((AppCapacitySnapshot.capacity_status == "ATENCAO", 1), else_=0)
        ).label("warning_total"),
        func.sum(
            case((AppCapacitySnapshot.capacity_status == "CRITICO", 1), else_=0)
        ).label("critical_total"),
        func.sum(
            case((AppCapacitySnapshot.capacity_status == "SATURADO", 1), else_=0)
        ).label("saturated_total"),
    )            .filter(AppCapacitySnapshot.collected_at >= since)
            .group_by(AppCapacitySnapshot.run_id)
            .order_by(func.min(AppCapacitySnapshot.collected_at).asc())
            .all()
        )

        series = []
        for row in rows:
            series.append(
                {
                    "run_id": row.run_id,
                    "collected_at": row.collected_at.isoformat() if row.collected_at else None,
                    "applications_total": int(row.applications_total or 0),
                    "avg_score": round(float(row.avg_score or 0), 2),
                    "healthy_total": int(row.healthy_total or 0),
                    "warning_total": int(row.warning_total or 0),
                    "critical_total": int(row.critical_total or 0),
                    "saturated_total": int(row.saturated_total or 0),
                }
            )

        latest_risky = (
            self.db.query(AppCapacitySnapshot)
            .filter(AppCapacitySnapshot.collected_at >= since)
            .order_by(AppCapacitySnapshot.collected_at.desc(), AppCapacitySnapshot.capacity_score.asc())
            .limit(20)
            .all()
        )

        latest_risky_rows = [
            {
                "collected_at": item.collected_at.isoformat() if item.collected_at else None,
                "application": item.application,
                "project": item.project,
                "namespace": item.namespace,
                "capacity_score": item.capacity_score,
                "capacity_status": item.capacity_status,
                "sync_status": item.sync_status,
                "health_status": item.health_status,
            }
            for item in latest_risky
        ]

        return {
            "days": days,
            "runs_total": len(series),
            "series": series,
            "latest_risky_rows": latest_risky_rows,
        }

    def render_dashboard_html(self) -> str:
        return """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CMDB Capacity Dashboard</title>
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
      max-width: 1600px;
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
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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
      grid-template-columns: 2fr 1fr;
      gap: 18px;
      margin-bottom: 18px;
    }

    .grid-panels {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-bottom: 18px;
    }

    .panel h3 {
      margin-top: 0;
      margin-bottom: 14px;
      font-size: 16px;
    }

    .bar-row {
      margin-bottom: 12px;
    }

    .bar-label {
      display: flex;
      justify-content: space-between;
      margin-bottom: 6px;
      font-size: 13px;
      color: var(--muted);
      gap: 10px;
    }

    .bar-track {
      width: 100%;
      height: 14px;
      background: #0f141a;
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid var(--border);
    }

    .bar-fill {
      height: 100%;
      border-radius: 999px;
    }

    .line-chart {
      display: flex;
      align-items: end;
      gap: 8px;
      min-height: 220px;
      padding-top: 10px;
      overflow-x: auto;
    }

    .line-bar-wrap {
      min-width: 52px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
    }

    .line-bar {
      width: 36px;
      background: var(--blue);
      border-radius: 8px 8px 0 0;
    }

    .line-caption {
      font-size: 11px;
      color: var(--muted);
      text-align: center;
      word-break: break-word;
    }

    .table-wrap {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }

    th, td {
      border-bottom: 1px solid var(--border);
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }

    th {
      color: var(--muted);
      font-weight: 600;
    }

    .status {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }

    .SAUDAVEL { background: rgba(41, 156, 70, 0.2); color: #7ee787; }
    .ATENCAO { background: rgba(224, 180, 0, 0.2); color: #ffd866; }
    .CRITICO { background: rgba(212, 74, 58, 0.2); color: #ff7b72; }
    .SATURADO { background: rgba(143, 59, 184, 0.2); color: #d2a8ff; }

    .muted {
      color: var(--muted);
    }

    .small {
      font-size: 12px;
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
        <div class="title">CMDB Capacity Dashboard</div>
        <div class="muted small">Argo CD + PostgreSQL snapshots</div>
      </div>
      <div class="actions">
        <button onclick="collectNow()">Coletar agora</button>
        <button onclick="loadAll()">Atualizar dashboard</button>
      </div>
    </div>

    <div id="cards" class="grid-cards"></div>

    <div class="grid-main">
      <div class="panel">
        <h3>Evolução do Score Médio por Coleta</h3>
        <div id="historyChart" class="line-chart"></div>
      </div>
      <div class="panel">
        <h3>Indicadores</h3>
        <div id="gauges"></div>
      </div>
    </div>

    <div class="grid-panels">
      <div class="panel">
        <h3>Status de Capacity</h3>
        <div id="capacityBars"></div>
      </div>
      <div class="panel">
        <h3>Status de Sync</h3>
        <div id="syncBars"></div>
      </div>
    </div>

    <div class="grid-panels">
      <div class="panel">
        <h3>Status de Health</h3>
        <div id="healthBars"></div>
      </div>
      <div class="panel">
        <h3>Top Projetos</h3>
        <div id="projectBars"></div>
      </div>
    </div>

    <div class="panel" style="margin-bottom:18px;">
      <h3>Top Applications em Risco</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Application</th>
              <th>Projeto</th>
              <th>Namespace</th>
              <th>Score</th>
              <th>Status</th>
              <th>Sync</th>
              <th>Health</th>
              <th>Operation</th>
              <th>Reasons</th>
            </tr>
          </thead>
          <tbody id="riskTable"></tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <h3>Operações com Falha</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Application</th>
              <th>Phase</th>
              <th>Duração (s)</th>
              <th>Mensagem</th>
            </tr>
          </thead>
          <tbody id="failedOpsTable"></tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    function statusColor(name) {
      if (name === "SAUDAVEL") return "var(--green)";
      if (name === "ATENCAO") return "var(--yellow)";
      if (name === "CRITICO") return "var(--red)";
      if (name === "SATURADO") return "var(--purple)";
      return "var(--blue)";
    }

    function createCard(label, value) {
      return `
        <div class="card">
          <div class="label">${label}</div>
          <div class="value">${value}</div>
        </div>
      `;
    }

    function renderBars(targetId, data, colorFallback = "var(--blue)") {
      const target = document.getElementById(targetId);
      const entries = Object.entries(data || {});
      const max = Math.max(...entries.map(([, v]) => Number(v || 0)), 1);

      target.innerHTML = entries.map(([label, value]) => {
        const pct = (Number(value || 0) / max) * 100;
        const fillColor = targetId === "capacityBars" ? statusColor(label) : colorFallback;
        return `
          <div class="bar-row">
            <div class="bar-label">
              <span>${label}</span>
              <span>${value}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" style="width:${pct}%; background:${fillColor};"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    function renderHistory(series) {
      const target = document.getElementById("historyChart");
      if (!series || !series.length) {
        target.innerHTML = '<div class="muted">Sem histórico ainda. Execute uma coleta.</div>';
        return;
      }

      target.innerHTML = series.map(item => {
        const height = Math.max(8, Math.round((Number(item.avg_score || 0) / 100) * 180));
        const label = (item.collected_at || "").slice(5, 16).replace("T", " ");
        return `
          <div class="line-bar-wrap">
            <div class="small">${item.avg_score}</div>
            <div class="line-bar" style="height:${height}px;"></div>
            <div class="line-caption">${label}</div>
          </div>
        `;
      }).join("");
    }

    function renderCards(cards) {
      const target = document.getElementById("cards");
      target.innerHTML = [
        createCard("Applications", cards.applications_total ?? 0),
        createCard("Score Médio", cards.capacity_score_avg ?? 0),
        createCard("Saudáveis", cards.healthy_total ?? 0),
        createCard("Atenção", cards.warning_total ?? 0),
        createCard("Críticas", cards.critical_total ?? 0),
        createCard("Saturadas", cards.saturated_total ?? 0),
        createCard("OutOfSync", cards.out_of_sync_total ?? 0),
        createCard("Degraded", cards.degraded_total ?? 0),
        createCard("Falhas", cards.failed_operations_total ?? 0)
      ].join("");
    }

    function renderGauges(gauges) {
      const target = document.getElementById("gauges");
      target.innerHTML = `
        <div class="bar-row">
          <div class="bar-label"><span>Auto Sync</span><span>${gauges.auto_sync_enabled_percent ?? 0}%</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${gauges.auto_sync_enabled_percent ?? 0}%; background:var(--blue)"></div></div>
        </div>
        <div class="bar-row">
          <div class="bar-label"><span>Self Heal</span><span>${gauges.self_heal_enabled_percent ?? 0}%</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${gauges.self_heal_enabled_percent ?? 0}%; background:var(--orange)"></div></div>
        </div>
        <div class="bar-row">
          <div class="bar-label"><span>Healthy</span><span>${gauges.healthy_percent ?? 0}%</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${gauges.healthy_percent ?? 0}%; background:var(--green)"></div></div>
        </div>
        <div class="bar-row">
          <div class="bar-label"><span>Crítico/Saturado</span><span>${gauges.critical_percent ?? 0}%</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${gauges.critical_percent ?? 0}%; background:var(--red)"></div></div>
        </div>
      `;
    }

    function renderRiskTable(rows) {
      const target = document.getElementById("riskTable");
      target.innerHTML = (rows || []).map(row => `
        <tr>
          <td>${row.application ?? ""}</td>
          <td>${row.project ?? ""}</td>
          <td>${row.namespace ?? ""}</td>
          <td>${row.capacity_score ?? ""}</td>
          <td><span class="status ${row.capacity_status}">${row.capacity_status}</span></td>
          <td>${row.sync_status ?? ""}</td>
          <td>${row.health_status ?? ""}</td>
          <td>${row.operation_phase ?? ""}</td>
          <td>${(row.reasons || []).join(", ")}</td>
        </tr>
      `).join("");
    }

    function renderFailedOps(rows) {
      const target = document.getElementById("failedOpsTable");
      target.innerHTML = (rows || []).map(row => `
        <tr>
          <td>${row.application ?? ""}</td>
          <td>${row.operation_phase ?? ""}</td>
          <td>${row.operation_duration_seconds ?? ""}</td>
          <td>${row.operation_message ?? ""}</td>
        </tr>
      `).join("");
    }

    async function loadDashboard() {
      const response = await fetch('/applications/capacity/dashboard');
      return await response.json();
    }

    async function loadHistory() {
      const response = await fetch('/applications/capacity/history?days=30');
      return await response.json();
    }

    async function loadAll() {
      const [dashboard, history] = await Promise.all([loadDashboard(), loadHistory()]);
      renderCards(dashboard.cards || {});
      renderGauges(dashboard.gauges || {});
      renderBars('capacityBars', dashboard.bars?.by_capacity_status || {});
      renderBars('syncBars', dashboard.bars?.by_sync_status || {}, 'var(--blue)');
      renderBars('healthBars', dashboard.bars?.by_health_status || {}, 'var(--orange)');
      renderBars('projectBars', dashboard.bars?.top_projects || {}, 'var(--purple)');
      renderRiskTable(dashboard.tables?.top_risky_applications || []);
      renderFailedOps(dashboard.tables?.failed_operations || []);
      renderHistory(history.series || []);
    }

    async function collectNow() {
      await fetch('/applications/capacity/collect', { method: 'POST' });
      await loadAll();
      alert('Coleta concluída.');
    }

    loadAll();
  </script>
</body>
</html>
        """
