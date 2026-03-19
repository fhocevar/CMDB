from datetime import datetime

from pydantic import BaseModel


class MetricCreate(BaseModel):
    asset_id: int
    metric_type: str
    metric_value: float
    metric_unit: str
    collected_at: datetime
    source: str


class MetricResponse(MetricCreate):
    id: int

    class Config:
        from_attributes = True
