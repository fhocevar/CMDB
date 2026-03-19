from pydantic import BaseModel


class DiscoveryRunResponse(BaseModel):
    source_name: str
    status: str
    assets_found: int
    assets_updated: int
    message: str
