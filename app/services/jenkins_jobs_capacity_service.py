from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.jenkins_job_capacity_snapshot import JenkinsJobCapacitySnapshot


class JenkinsJobsCapacityService:
    def __init__(self, db: Session):
        self.db = db

    def collect_and_persist_jobs_snapshot(self, max_jobs: int = 20) -> dict[str, Any]:
        data = self._collect_jobs_from_jenkins(max_jobs=max_jobs)

        jobs = data.get("jobs", [])
        persisted = 0

        for job in jobs:
            last_build = job.get("lastBuild") or {}
            build_info = last_build.get("_details") or {}

            timestamp_ms = build_info.get("timestamp")
            duration_ms = build_info.get("duration")
            estimated_ms = build_info.get("estimatedDuration")

            start_dt = self._from_millis(timestamp_ms)
            end_dt = self._from_millis(timestamp_ms + duration_ms) if timestamp_ms and duration_ms is not None else None

            snapshot = JenkinsJobCapacitySnapshot(
                provider="JENKINS",
                snapshot_type="jenkins_job_capacity",
                job_name=job.get("name"),
                build_number=build_info.get("number"),
                result=build_info.get("result"),
                status="building" if build_info.get("building") else "completed",
                built_on=build_info.get("builtOn"),
                duration_seconds=self._ms_to_seconds(duration_ms),
                estimated_duration_seconds=self._ms_to_seconds(estimated_ms),
                queue_seconds=None,
                timestamp_start=start_dt,
                timestamp_end=end_dt,
                build_url=build_info.get("url"),
                is_building=str(build_info.get("building", False)),
                raw_json=build_info,
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

            jobs.append(
                {
                    "job_name": job_name,
                    "runs": len(items),
                    "failures": len(failures),
                    "avg_duration_seconds": round(sum(durations) / len(durations), 2) if durations else 0.0,
                    "max_duration_seconds": round(max(durations), 2) if durations else 0.0,
                    "main_agent": self._most_common(built_on_values),
                    "last_result": items[0].result if items else None,
                    "last_build_number": items[0].build_number if items else None,
                }
            )

        jobs = sorted(jobs, key=lambda x: (-x["avg_duration_seconds"], -x["failures"], x["job_name"]))

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_job_capacity",
            "jobs": jobs,
        }

    def _collect_jobs_from_jenkins(self, max_jobs: int = 20) -> dict[str, Any]:
        base_url = str(settings.JENKINS_URL).rstrip("/")
        auth = None

        if getattr(settings, "JENKINS_USER", None) and getattr(settings, "JENKINS_PASSWORD", None):
            auth = (settings.JENKINS_USER, settings.JENKINS_PASSWORD)

        verify = bool(getattr(settings, "JENKINS_VERIFY_TLS", True))

        jobs_url = (
            f"{base_url}/api/json"
            "?tree=jobs[name,url,color,lastBuild[url]]"
        )

        response = requests.get(jobs_url, auth=auth, verify=verify, timeout=60)
        response.raise_for_status()

        payload = response.json()
        jobs = payload.get("jobs", [])[:max_jobs]

        enriched_jobs = []
        for job in jobs:
            last_build = job.get("lastBuild")
            details = {}

            if last_build and last_build.get("url"):
                build_api_url = (
                    f"{str(last_build['url']).rstrip('/')}/api/json"
                    "?tree=number,result,duration,timestamp,estimatedDuration,builtOn,building,url"
                )
                try:
                    build_response = requests.get(build_api_url, auth=auth, verify=verify, timeout=60)
                    build_response.raise_for_status()
                    details = build_response.json()
                except Exception:
                    details = {}

            job_copy = dict(job)
            if "lastBuild" not in job_copy or job_copy["lastBuild"] is None:
                job_copy["lastBuild"] = {}
            job_copy["lastBuild"]["_details"] = details
            enriched_jobs.append(job_copy)

        return {"jobs": enriched_jobs}

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