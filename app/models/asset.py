from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    hostname: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    environment: Mapped[str] = mapped_column(String(30), nullable=False)
    criticality: Mapped[str] = mapped_column(String(20), nullable=False)
    business_service: Mapped[str] = mapped_column(String(150), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    operating_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cpu_cores: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_gb: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    disk_gb: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    network_mbps: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    cluster_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    namespace: Mapped[str | None] = mapped_column(String(150), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="MANUAL")
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    labels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    metrics = relationship("Metric", back_populates="asset")
    parent = relationship("Asset", remote_side=[id], backref="children")
