from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AppCapacitySnapshot(Base):
    __tablename__ = "app_capacity_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    application: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    project: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    namespace: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    destination_server: Mapped[str | None] = mapped_column(String(500), nullable=True)
    destination_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    repo: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chart: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    has_multiple_sources: Mapped[bool] = mapped_column(default=False, nullable=False)
    sources_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sync_status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    health_status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    sync_revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_revision: Mapped[str | None] = mapped_column(String(255), nullable=True)

    operation_phase: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    operation_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    operation_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    operation_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    operation_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    automated_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    prune_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    self_heal_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    allow_empty_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    retry_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)

    sync_options: Mapped[list | None] = mapped_column(JSON, nullable=True)

    resources_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resource_kinds: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resources_degraded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resources_missing: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resources_out_of_sync: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resources_unknown: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resources: Mapped[list | None] = mapped_column(JSON, nullable=True)

    conditions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    conditions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    images_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    external_urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    external_urls_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    capacity_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    capacity_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)