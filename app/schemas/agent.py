from datetime import datetime

from pydantic import BaseModel


class AgentRegisterRequest(BaseModel):
    agent_token: str
    agent_version: str
    hostname: str
    operating_system: str
    ip_address: str | None = None
    environment: str = "PRD"
    criticality: str = "MEDIA"
    business_service: str = "INFRAESTRUTURA"
    cpu_cores: int
    memory_gb: float
    disk_gb: float
    network_mbps: float
    asset_type: str = "SERVER"


class AgentHeartbeatRequest(BaseModel):
    agent_token: str
    hostname: str
    ip_address: str | None = None
    collected_at: datetime


class AgentMetricBatchItem(BaseModel):
    metric_type: str
    metric_value: float
    metric_unit: str


class DockerContainerMetricItem(BaseModel):
    container_id: str
    container_name: str
    cpu_percent: float
    memory_percent: float
    network_percent: float


class AgentMetricBatchRequest(BaseModel):
    agent_token: str
    collected_at: datetime
    metrics: list[AgentMetricBatchItem]
    docker_containers: list[DockerContainerMetricItem] = []
