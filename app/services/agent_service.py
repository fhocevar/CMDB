from datetime import datetime

from sqlalchemy.orm import Session

from app.integrations.docker_host_client import ingest_docker_container_metrics
from app.models.asset import Asset
from app.models.collector_agent import CollectorAgent
from app.schemas.agent import AgentHeartbeatRequest, AgentMetricBatchRequest, AgentRegisterRequest
from app.schemas.asset import AssetCreate
from app.schemas.metric import MetricCreate
from app.services.asset_service import upsert_asset
from app.services.metric_service import ingest_metric, update_baseline


def register_agent(db: Session, payload: AgentRegisterRequest) -> dict:
    asset_payload = AssetCreate(
        hostname=payload.hostname,
        asset_type=payload.asset_type,
        environment=payload.environment,
        criticality=payload.criticality,
        business_service=payload.business_service,
        ip_address=payload.ip_address,
        operating_system=payload.operating_system,
        cpu_cores=payload.cpu_cores,
        memory_gb=payload.memory_gb,
        disk_gb=payload.disk_gb,
        network_mbps=payload.network_mbps,
        source="AGENT",
        provider="HOST",
    )

    asset, _ = upsert_asset(db, asset_payload)

    agent = db.query(CollectorAgent).filter(CollectorAgent.agent_token == payload.agent_token).first()
    if not agent:
        agent = CollectorAgent(
            asset_id=asset.id,
            agent_token=payload.agent_token,
            agent_version=payload.agent_version,
            hostname=payload.hostname,
            operating_system=payload.operating_system,
            ip_address=payload.ip_address,
            last_heartbeat=datetime.utcnow(),
            status="ONLINE",
        )
        db.add(agent)
    else:
        agent.asset_id = asset.id
        agent.agent_version = payload.agent_version
        agent.hostname = payload.hostname
        agent.operating_system = payload.operating_system
        agent.ip_address = payload.ip_address
        agent.last_heartbeat = datetime.utcnow()
        agent.status = "ONLINE"

    db.commit()
    return {"message": "Agent registrado com sucesso", "asset_id": asset.id}


def heartbeat_agent(db: Session, payload: AgentHeartbeatRequest) -> dict:
    agent = db.query(CollectorAgent).filter(CollectorAgent.agent_token == payload.agent_token).first()
    if not agent:
        return {"message": "Agent não encontrado", "status": "NOT_FOUND"}

    agent.last_heartbeat = payload.collected_at
    agent.hostname = payload.hostname
    agent.ip_address = payload.ip_address
    agent.status = "ONLINE"

    if agent.asset_id:
        asset = db.query(Asset).filter(Asset.id == agent.asset_id).first()
        if asset:
            asset.last_seen_at = payload.collected_at

    db.commit()
    return {"message": "Heartbeat recebido", "status": "OK"}


def ingest_agent_metrics(db: Session, payload: AgentMetricBatchRequest) -> dict:
    agent = db.query(CollectorAgent).filter(CollectorAgent.agent_token == payload.agent_token).first()
    if not agent or not agent.asset_id:
        return {"message": "Agent não registrado", "status": "NOT_FOUND"}

    asset = db.query(Asset).filter(Asset.id == agent.asset_id).first()
    if not asset:
        return {"message": "Asset do agent não encontrado", "status": "NOT_FOUND"}

    for metric in payload.metrics:
        ingest_metric(
            db,
            MetricCreate(
                asset_id=agent.asset_id,
                metric_type=metric.metric_type,
                metric_value=metric.metric_value,
                metric_unit=metric.metric_unit,
                collected_at=payload.collected_at,
                source="AGENT",
            ),
        )
        update_baseline(db, agent.asset_id, metric.metric_type)

    for container in payload.docker_containers:
        ingest_docker_container_metrics(
            db=db,
            host_asset_id=asset.id,
            hostname=asset.hostname,
            container_id=container.container_id,
            container_name=container.container_name,
            cpu_percent=container.cpu_percent,
            memory_percent=container.memory_percent,
            network_percent=container.network_percent,
            environment=asset.environment,
            business_service=asset.business_service,
        )

    return {"message": "Métricas recebidas", "status": "OK", "asset_id": agent.asset_id}
