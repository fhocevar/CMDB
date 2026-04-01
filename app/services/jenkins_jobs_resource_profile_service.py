from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.jenkins_capacity_snapshot import JenkinsCapacitySnapshot
from app.models.jenkins_job_capacity_snapshot import JenkinsJobCapacitySnapshot


class JenkinsJobsResourceProfileService:
    def __init__(self, db: Session):
        self.db = db

    def get_jobs_resource_profiles(
        self,
        limit: int = 100,
        padding_minutes: int = 10,
    ) -> dict[str, Any]:
        jobs = (
            self.db.query(JenkinsJobCapacitySnapshot)
            .order_by(JenkinsJobCapacitySnapshot.created_at.desc())
            .limit(limit)
            .all()
        )

        items: list[dict[str, Any]] = []
        correlated_count = 0

        for job in jobs:
            profile = self._build_job_resource_profile(
                job=job,
                padding_minutes=padding_minutes,
            )
            if profile.get("correlated"):
                correlated_count += 1
            items.append(profile)

        return {
            "status": "OK",
            "provider": "JENKINS",
            "snapshot_type": "jenkins_job_resource_profile",
            "count": len(items),
            "correlated_count": correlated_count,
            "items": items,
        }

    def _build_job_resource_profile(
        self,
        job: JenkinsJobCapacitySnapshot,
        padding_minutes: int,
    ) -> dict[str, Any]:
        built_on = (job.built_on or "").strip()

        if not built_on:
            return self._base_profile(
                job=job,
                correlated=False,
                message="Job sem agent/built_on para correlação.",
            )

        window_start, window_end = self._resolve_job_window(job)
        padded_start = window_start - timedelta(minutes=padding_minutes)
        padded_end = window_end + timedelta(minutes=padding_minutes)

        snapshots = (
            self.db.query(JenkinsCapacitySnapshot)
            .filter(JenkinsCapacitySnapshot.created_at >= padded_start)
            .filter(JenkinsCapacitySnapshot.created_at <= padded_end)
            .order_by(JenkinsCapacitySnapshot.created_at.asc())
            .all()
        )

        series: list[dict[str, Any]] = []

        for snap in snapshots:
            agents = snap.agents_json or []
            matched_agent = self._find_agent_in_snapshot(agents, built_on)
            if not matched_agent:
                continue

            series.append(
                {
                    "snapshot_time": snap.created_at.isoformat() if snap.created_at else None,
                    "cpu_operational_percent": self._to_float(matched_agent.get("cpu_operational_percent")),
                    "memory_used_percent": self._to_float(matched_agent.get("memory_used_percent")),
                    "disk_free_gb": self._to_float(matched_agent.get("disk_free_gb")),
                    "memory_has_real_data": bool(matched_agent.get("memory_has_real_data")),
                    "disk_has_real_data": bool(matched_agent.get("disk_has_real_data")),
                    "cpu_has_real_data": bool(matched_agent.get("cpu_has_real_data")),
                }
            )

        if not series:
            return self._base_profile(
                job=job,
                correlated=False,
                message="Nenhum snapshot do agent foi encontrado no período da execução.",
            )

        cpu_values = [row["cpu_operational_percent"] for row in series if row["cpu_operational_percent"] is not None]
        memory_values = [
            row["memory_used_percent"]
            for row in series
            if row["memory_has_real_data"] and row["memory_used_percent"] is not None
        ]
        disk_values = [
            row["disk_free_gb"]
            for row in series
            if row["disk_has_real_data"] and row["disk_free_gb"] is not None
        ]

        avg_cpu = self._avg(cpu_values)
        avg_memory = self._avg(memory_values)
        min_disk = self._min(disk_values)
        disk_delta = self._delta(disk_values)

        risk_level, risk_reasons = self._classify_risk(
            avg_cpu=avg_cpu,
            avg_memory=avg_memory,
            min_disk=min_disk,
            disk_delta=disk_delta,
        )

        profile = self._base_profile(
            job=job,
            correlated=True,
            message="Perfil de recurso correlacionado com snapshots do agent.",
        )
        profile.update(
            {
                "window_start": window_start.isoformat() if window_start else None,
                "window_end": window_end.isoformat() if window_end else None,
                "matching_snapshots": len(series),
                "avg_cpu_operational_percent_during_job": avg_cpu,
                "avg_memory_used_percent_during_job": avg_memory,
                "min_disk_free_gb_during_job": min_disk,
                "disk_free_delta_gb_during_job": disk_delta,
                "risk_level": risk_level,
                "risk_reasons": risk_reasons,
                "series": series,
            }
        )
        return profile

    def _base_profile(
        self,
        job: JenkinsJobCapacitySnapshot,
        correlated: bool,
        message: str,
    ) -> dict[str, Any]:
        return {
            "job_snapshot_id": job.id,
            "job_name": job.job_name,
            "build_number": job.build_number,
            "result": job.result,
            "status": job.status,
            "built_on": job.built_on,
            "duration_seconds": self._to_float(job.duration_seconds),
            "timestamp_start": job.timestamp_start.isoformat() if job.timestamp_start else None,
            "timestamp_end": job.timestamp_end.isoformat() if job.timestamp_end else None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "correlated": correlated,
            "message": message,
            "avg_cpu_operational_percent_during_job": None,
            "avg_memory_used_percent_during_job": None,
            "min_disk_free_gb_during_job": None,
            "disk_free_delta_gb_during_job": None,
            "risk_level": "unknown" if not correlated else "ok",
            "risk_reasons": [],
            "matching_snapshots": 0,
            "series": [],
        }

    def _resolve_job_window(
        self,
        job: JenkinsJobCapacitySnapshot,
    ) -> tuple[datetime, datetime]:
        fallback_point = job.created_at or datetime.now(timezone.utc)

        start = job.timestamp_start or fallback_point
        end = job.timestamp_end

        if end is None:
            duration_seconds = self._to_float(job.duration_seconds)
            if duration_seconds and duration_seconds > 0:
                end = start + timedelta(seconds=duration_seconds)
            else:
                end = start + timedelta(minutes=15)

        if end < start:
            end = start

        return start, end

    def _find_agent_in_snapshot(
        self,
        agents: list[dict[str, Any]],
        built_on: str,
    ) -> dict[str, Any] | None:
        target = built_on.strip().lower()

        for agent in agents:
            name = str(agent.get("name") or "").strip().lower()
            if name == target:
                return agent

        return None

    def _classify_risk(
        self,
        avg_cpu: float | None,
        avg_memory: float | None,
        min_disk: float | None,
        disk_delta: float | None,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        level = "ok"

        if min_disk is not None:
            if min_disk <= 5:
                level = "critical"
                reasons.append(f"Disco livre mínimo crítico ({min_disk:.2f} GB).")
            elif min_disk <= 10:
                if level != "critical":
                    level = "warning"
                reasons.append(f"Disco livre mínimo baixo ({min_disk:.2f} GB).")

        if avg_memory is not None:
            if avg_memory >= 95:
                level = "critical"
                reasons.append(f"Memória média crítica ({avg_memory:.2f}%).")
            elif avg_memory >= 85:
                if level != "critical":
                    level = "warning"
                reasons.append(f"Memória média alta ({avg_memory:.2f}%).")

        if avg_cpu is not None:
            if avg_cpu >= 95:
                level = "critical"
                reasons.append(f"CPU operacional média crítica ({avg_cpu:.2f}%).")
            elif avg_cpu >= 85:
                if level != "critical":
                    level = "warning"
                reasons.append(f"CPU operacional média alta ({avg_cpu:.2f}%).")

        if disk_delta is not None and disk_delta <= -5:
            if level != "critical":
                level = "warning"
            reasons.append(f"Queda relevante de disco durante o job ({disk_delta:.2f} GB).")

        return level, reasons

    def _avg(self, values: list[float]) -> float | None:
        valid = [float(v) for v in values if v is not None]
        if not valid:
            return None
        return round(sum(valid) / len(valid), 2)

    def _min(self, values: list[float]) -> float | None:
        valid = [float(v) for v in values if v is not None]
        if not valid:
            return None
        return round(min(valid), 2)

    def _delta(self, values: list[float]) -> float | None:
        valid = [float(v) for v in values if v is not None]
        if len(valid) < 2:
            return None
        return round(valid[-1] - valid[0], 2)

    def _to_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return round(float(value), 2)
        except Exception:
            return None