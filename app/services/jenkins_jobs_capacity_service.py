from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.jenkins_job_capacity_snapshot import JenkinsJobCapacitySnapshot


class JenkinsJobsCapacityService:
    def __init__(self, db: Session):
        self.db = db

    def collect_and_persist_jobs_snapshot(self, max_jobs: int = 500) -> dict[str, Any]:
        data = self._collect_jobs_from_jenkins(max_jobs=max_jobs)

        jobs = data.get("jobs", [])
        persisted = 0
        detailed_jobs = 0
        jobs_with_detail_error = 0

        for job in jobs:
            selected_build = job.get("_selected_build") or {}
            build_info = selected_build.get("_details") or {}
            details_meta = selected_build.get("_details_meta") or {}

            build_number = (
                build_info.get("number")
                or selected_build.get("number")
            )

            result = build_info.get("result")
            built_on = build_info.get("builtOn")
            build_url = build_info.get("url") or selected_build.get("url")

            timestamp_ms = build_info.get("timestamp")
            duration_ms = build_info.get("duration")
            estimated_ms = build_info.get("estimatedDuration")

            is_building = bool(build_info.get("building", False))
            details_collected = bool(build_info)
            detail_error = bool(details_meta.get("error"))

            if details_collected:
                detailed_jobs += 1

            if detail_error:
                jobs_with_detail_error += 1

            status = self._derive_status(
                result=result,
                is_building=is_building,
                has_build=bool(build_number or build_url),
                details_collected=details_collected,
                detail_error=detail_error,
            )

            start_dt = self._from_millis(timestamp_ms)
            end_dt = (
                self._from_millis(timestamp_ms + duration_ms)
                if timestamp_ms is not None and duration_ms is not None
                else None
            )

            snapshot = JenkinsJobCapacitySnapshot(
                provider="JENKINS",
                snapshot_type="jenkins_job_capacity",
                job_name=job.get("name"),
                build_number=build_number,
                result=result,
                status=status,
                built_on=built_on,
                duration_seconds=self._ms_to_seconds(duration_ms),
                estimated_duration_seconds=self._ms_to_seconds(estimated_ms),
                queue_seconds=None,
                timestamp_start=start_dt,
                timestamp_end=end_dt,
                build_url=build_url,
                is_building=str(is_building),
                raw_json={
                    "job": {
                        "name": job.get("name"),
                        "url": job.get("url"),
                        "color": job.get("color"),
                    },
                    "selected_build": {
                        "source": selected_build.get("source"),
                        "number": selected_build.get("number"),
                        "url": selected_build.get("url"),
                    },
                    "details_collected": details_collected,
                    "details_meta": details_meta,
                    "details": build_info,
                },
            )

            self.db.add(snapshot)
            persisted += 1

        self.db.commit()

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_job_capacity",
            "jobs_found": len(jobs),
            "jobs_persisted": persisted,
            "jobs_with_details": detailed_jobs,
            "jobs_with_detail_error": jobs_with_detail_error,
        }

    def get_jobs_history(self, limit: int = 100) -> dict[str, Any]:
        rows = (
            self.db.query(JenkinsJobCapacitySnapshot)
            .order_by(JenkinsJobCapacitySnapshot.created_at.desc())
            .limit(limit)
            .all()
        )

        items = []
        for row in rows:
            raw_json = row.raw_json or {}
            details_collected = bool(raw_json.get("details_collected", False))
            details_meta = raw_json.get("details_meta") or {}

            items.append(
                {
                    "id": row.id,
                    "job_name": row.job_name,
                    "build_number": row.build_number,
                    "result": row.result,
                    "status": row.status,
                    "built_on": row.built_on,
                    "duration_seconds": row.duration_seconds,
                    "estimated_duration_seconds": row.estimated_duration_seconds,
                    "queue_seconds": row.queue_seconds,
                    "timestamp_start": row.timestamp_start.isoformat() if row.timestamp_start else None,
                    "timestamp_end": row.timestamp_end.isoformat() if row.timestamp_end else None,
                    "build_url": row.build_url,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "details_collected": details_collected,
                    "details_meta": details_meta,
                }
            )

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_job_capacity",
            "count": len(items),
            "items": items,
        }

    def get_jobs_summary(self, limit: int = 200) -> dict[str, Any]:
        rows = (
            self.db.query(JenkinsJobCapacitySnapshot)
            .order_by(JenkinsJobCapacitySnapshot.created_at.desc())
            .limit(limit)
            .all()
        )

        grouped: dict[str, list[JenkinsJobCapacitySnapshot]] = {}
        for row in rows:
            grouped.setdefault(row.job_name, []).append(row)

        jobs = []
        for job_name, items in grouped.items():
            durations = [float(x.duration_seconds or 0) for x in items if x.duration_seconds is not None]
            failures = [x for x in items if (x.result or "").upper() not in ("SUCCESS", "")]
            built_on_values = [x.built_on for x in items if x.built_on]
            build_numbers = [x.build_number for x in items if x.build_number is not None]

            detailed_count = sum(
                1
                for x in items
                if bool((x.raw_json or {}).get("details_collected", False))
            )

            detail_error_count = sum(
                1
                for x in items
                if bool(((x.raw_json or {}).get("details_meta") or {}).get("error"))
            )

            latest_details_meta = (items[0].raw_json or {}).get("details_meta") or {}

            jobs.append(
                {
                    "job_name": job_name,
                    "runs": len(items),
                    "failures": len(failures),
                    "avg_duration_seconds": round(sum(durations) / len(durations), 2) if durations else 0.0,
                    "max_duration_seconds": round(max(durations), 2) if durations else 0.0,
                    "main_agent": self._most_common(built_on_values),
                    "last_result": items[0].result if items else None,
                    "last_build_number": max(build_numbers) if build_numbers else None,
                    "details_collected_count": detailed_count,
                    "detail_error_count": detail_error_count,
                    "last_detail_error": latest_details_meta.get("error"),
                    "last_detail_status_code": latest_details_meta.get("status_code"),
                }
            )

        jobs = sorted(
            jobs,
            key=lambda x: (
                -x["details_collected_count"],
                x["detail_error_count"],
                -x["avg_duration_seconds"],
                -x["failures"],
                x["job_name"],
            ),
        )

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_job_capacity",
            "jobs": jobs,
        }

    def _collect_jobs_from_jenkins(self, max_jobs: int = 500) -> dict[str, Any]:
        base_url = str(settings.JENKINS_URL).rstrip("/")
        auth = None

        if getattr(settings, "JENKINS_USER", None) and getattr(settings, "JENKINS_PASSWORD", None):
            auth = (settings.JENKINS_USER, settings.JENKINS_PASSWORD)

        verify = bool(getattr(settings, "JENKINS_VERIFY_TLS", True))

        jobs_url = (
            f"{base_url}/api/json"
            "?tree=jobs[name,url,color,lastBuild[number,url],lastCompletedBuild[number,url]]"
        )

        response = requests.get(jobs_url, auth=auth, verify=verify, timeout=60)
        response.raise_for_status()

        payload = response.json()
        jobs = payload.get("jobs", [])[:max_jobs]

        enriched_jobs = []
        for job in jobs:
            job_copy = dict(job)

            last_build = job_copy.get("lastBuild") or {}
            last_completed_build = job_copy.get("lastCompletedBuild") or {}

            selected_build = self._pick_best_build_reference(
                last_build=last_build,
                last_completed_build=last_completed_build,
            )

            details = {}
            details_meta = {}
            selected_source = None

            if selected_build and selected_build.get("url"):
                selected_source = (
                    "lastBuild"
                    if selected_build.get("url") == last_build.get("url")
                    else "lastCompletedBuild"
                )
                details, details_meta = self._fetch_build_details(
                    build_url=selected_build.get("url"),
                    auth=auth,
                    verify=verify,
                )
            else:
                details_meta = {
                    "requested_url": None,
                    "normalized_url": None,
                    "final_url": None,
                    "status_code": None,
                    "error": "no_build_reference",
                    "message": "Nenhuma referência de build foi encontrada para o job.",
                }

            job_copy["_selected_build"] = {
                "source": selected_source,
                "number": selected_build.get("number"),
                "url": selected_build.get("url"),
                "_details": details or {},
                "_details_meta": details_meta or {},
            }

            enriched_jobs.append(job_copy)

        return {"jobs": enriched_jobs}

    def _fetch_build_details(
        self,
        build_url: str | None,
        auth: tuple[str, str] | None,
        verify: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not build_url:
            return {}, {
                "requested_url": None,
                "normalized_url": None,
                "final_url": None,
                "status_code": None,
                "error": "missing_build_url",
                "message": "URL da build não foi informada.",
            }

        normalized_build_url = self._normalize_build_url(build_url)
        build_api_url = (
            f"{normalized_build_url.rstrip('/')}/api/json"
            "?tree=number,result,duration,timestamp,estimatedDuration,builtOn,building,url"
        )

        try:
            build_response = requests.get(
                build_api_url,
                auth=auth,
                verify=verify,
                timeout=60,
                allow_redirects=True,
            )

            meta = {
                "requested_url": build_url,
                "normalized_url": normalized_build_url,
                "final_url": str(build_response.url),
                "status_code": build_response.status_code,
                "error": None,
                "message": "OK",
            }

            build_response.raise_for_status()
            payload = build_response.json()

            if not isinstance(payload, dict):
                meta["error"] = "invalid_payload"
                meta["message"] = "Payload retornado não é um objeto JSON."
                return {}, meta

            return payload, meta

        except requests.exceptions.HTTPError as exc:
            response = getattr(exc, "response", None)
            return {}, {
                "requested_url": build_url,
                "normalized_url": normalized_build_url,
                "final_url": str(response.url) if response is not None else None,
                "status_code": response.status_code if response is not None else None,
                "error": "http_error",
                "message": str(exc),
            }

        except requests.exceptions.Timeout as exc:
            return {}, {
                "requested_url": build_url,
                "normalized_url": normalized_build_url,
                "final_url": None,
                "status_code": None,
                "error": "timeout",
                "message": str(exc),
            }

        except requests.exceptions.RequestException as exc:
            return {}, {
                "requested_url": build_url,
                "normalized_url": normalized_build_url,
                "final_url": None,
                "status_code": None,
                "error": "request_exception",
                "message": str(exc),
            }

        except ValueError as exc:
            return {}, {
                "requested_url": build_url,
                "normalized_url": normalized_build_url,
                "final_url": None,
                "status_code": None,
                "error": "json_decode_error",
                "message": str(exc),
            }

        except Exception as exc:
            return {}, {
                "requested_url": build_url,
                "normalized_url": normalized_build_url,
                "final_url": None,
                "status_code": None,
                "error": "unexpected_error",
                "message": str(exc),
            }

    def _normalize_build_url(self, build_url: str) -> str:
        base_url = str(settings.JENKINS_URL).rstrip("/")
        parsed_base = urlparse(base_url)
        parsed_build = urlparse(str(build_url).strip())

        if not parsed_build.scheme or not parsed_build.netloc:
            path = str(build_url).strip()
            if not path.startswith("/"):
                path = f"/{path}"
            return f"{base_url}{path}"

        path = parsed_build.path or ""
        if parsed_build.query:
            path = f"{path}?{parsed_build.query}"

        return f"{parsed_base.scheme}://{parsed_base.netloc}{path}"

    def _pick_best_build_reference(
        self,
        last_build: dict[str, Any],
        last_completed_build: dict[str, Any],
    ) -> dict[str, Any]:
        if last_build and last_build.get("url"):
            return last_build

        if last_completed_build and last_completed_build.get("url"):
            return last_completed_build

        return {}

    def _derive_status(
        self,
        result: str | None,
        is_building: bool,
        has_build: bool,
        details_collected: bool,
        detail_error: bool,
    ) -> str:
        if is_building:
            return "building"

        if result:
            return "completed"

        if detail_error and has_build:
            return "detail_error"

        if details_collected and has_build:
            return "details_collected"

        if has_build:
            return "build_reference_only"

        return "no_build_data"

    def _ms_to_seconds(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return round(float(value) / 1000.0, 2)
        except Exception:
            return None

    def _from_millis(self, value: Any) -> datetime | None:
        try:
            if value is None:
                return None
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        except Exception:
            return None

    def _most_common(self, values: list[str]) -> str | None:
        if not values:
            return None

        counts: dict[str, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1

        return sorted(counts.items(), key=lambda x: (-x[1], x[0]))[0][0]