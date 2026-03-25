from collections import Counter
from datetime import datetime
from typing import Any

from app.integrations.argocd_client import ArgoCDClient


class ApplicationService:
    def __init__(self):
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

        result = []
        for item in conditions:
            result.append(
                {
                    "type": item.get("type"),
                    "message": item.get("message"),
                }
            )
        return result

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

    def _evaluate_capacity(self, sync_status: str | None, health_status: str | None) -> dict:
        reasons: list[str] = []

        sync_normalized = (sync_status or "Unknown").strip().lower()
        health_normalized = (health_status or "Unknown").strip().lower()

        if health_normalized == "degraded":
            reasons.append("Application Degraded")
        if health_normalized == "missing":
            reasons.append("Application Missing")
        if sync_normalized == "outofsync":
            reasons.append("Application OutOfSync")
        if health_normalized == "progressing":
            reasons.append("Application Progressing")
        if health_normalized == "suspended":
            reasons.append("Application Suspended")

        if health_normalized in {"degraded", "missing"}:
            status = "CRITICO"
        elif sync_normalized == "outofsync":
            status = "ATENCAO"
        elif health_normalized in {"progressing", "suspended", "unknown"}:
            status = "ATENCAO"
        else:
            status = "SAUDAVEL"

        return {
            "status": status,
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

        capacity = self._evaluate_capacity(sync_status, health_status)

        return {
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
            "capacity_status": capacity["status"],
            "reasons": capacity["reasons"],
        }

    def get_application_capacity(self, app_name: str):
        self._ensure_login()
        app = self.client.get_application(app_name)
        return self._build_application_result(app)

    def list_critical_apps(self):
        self._ensure_login()
        apps = self.client.list_applications()

        results = []
        for app in apps:
            name = app.get("metadata", {}).get("name")
            if not name:
                continue
            results.append(self._build_application_result(app))

        return results

    def summarize_applications(self):
        self._ensure_login()
        apps = self.client.list_applications()

        total = 0
        sync_counter = Counter()
        health_counter = Counter()
        capacity_counter = Counter()
        project_counter = Counter()
        namespace_counter = Counter()
        kind_counter = Counter()

        for app in apps:
            total += 1
            result = self._build_application_result(app)

            sync_counter[result["sync_status"] or "Unknown"] += 1
            health_counter[result["health_status"] or "Unknown"] += 1
            capacity_counter[result["capacity_status"]] += 1
            project_counter[result["project"] or "Unknown"] += 1
            namespace_counter[result["namespace"] or "Unknown"] += 1

            for kind, qty in result["resource_kinds"].items():
                kind_counter[kind] += qty

        return {
            "applications_total": total,
            "by_sync_status": dict(sync_counter),
            "by_health_status": dict(health_counter),
            "by_capacity_status": dict(capacity_counter),
            "top_projects": dict(project_counter.most_common(20)),
            "top_namespaces": dict(namespace_counter.most_common(20)),
            "resource_kinds_total": dict(kind_counter),
        }