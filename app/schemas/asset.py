from datetime import datetime

from pydantic import BaseModel


class AssetCreate(BaseModel):
    hostname: str
    asset_type: str
    environment: str
    criticality: str
    business_service: str
    ip_address: str | None = None
    operating_system: str | None = None
    cpu_cores: int
    memory_gb: float
    disk_gb: float
    network_mbps: float
    cluster_name: str | None = None
    namespace: str | None = None
    source: str = "MANUAL"
    provider: str | None = None
    external_id: str | None = None
    labels_json: str | None = None
    parent_asset_id: int | None = None
    is_active: bool = True


class AssetResponse(AssetCreate):
    id: int
    last_seen_at: datetime | None = None

    class Config:
        from_attributes = True
