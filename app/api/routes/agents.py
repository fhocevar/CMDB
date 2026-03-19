from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.agent import AgentHeartbeatRequest, AgentMetricBatchRequest, AgentRegisterRequest
from app.services.agent_service import heartbeat_agent, ingest_agent_metrics, register_agent

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.post("/register")
def register(payload: AgentRegisterRequest, db: Session = Depends(get_db)):
    return register_agent(db, payload)


@router.post("/heartbeat")
def heartbeat(payload: AgentHeartbeatRequest, db: Session = Depends(get_db)):
    return heartbeat_agent(db, payload)


@router.post("/metrics")
def metrics(payload: AgentMetricBatchRequest, db: Session = Depends(get_db)):
    return ingest_agent_metrics(db, payload)
