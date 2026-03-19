from sqlalchemy import Boolean, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ThresholdPolicy(Base):
    __tablename__ = "threshold_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)
    warning_percent: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    critical_percent: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    saturation_percent: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    trend_window_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
