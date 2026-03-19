from datetime import datetime

from pydantic import BaseModel


class CapacityStatusItem(BaseModel):
    asset_id: int
    hostname: str
    asset_type: str
    environment: str
    criticality: str
    business_service: str
    metric_type: str
    latest_value: float
    peak_value: float
    avg_value: float
    baseline_avg: float | None = None
    forecast_30d: float | None = None
    capacity_limit: float
    utilization_percent: float
    status: str
    trend: str
    collected_at: datetime


class DashboardSummary(BaseModel):
    total_assets: int
    healthy_assets: int
    warning_assets: int
    critical_assets: int
    saturated_assets: int
    items: list[CapacityStatusItem]
