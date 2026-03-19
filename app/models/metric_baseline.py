from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MetricBaseline(Base):
    __tablename__ = "metric_baselines"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)
    baseline_avg: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    baseline_peak: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    reference_window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
