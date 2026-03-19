from pydantic import BaseModel


class ThresholdPolicyCreate(BaseModel):
    asset_type: str
    metric_type: str
    warning_percent: float
    critical_percent: float
    saturation_percent: float
    trend_window_hours: int = 24
    is_active: bool = True


class ThresholdPolicyResponse(ThresholdPolicyCreate):
    id: int

    class Config:
        from_attributes = True
