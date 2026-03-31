from sqlalchemy import Column, Integer, String, DateTime, JSON, Float
from sqlalchemy.sql import func

from app.core.database import Base


class JenkinsJobCapacitySnapshot(Base):
    __tablename__ = "jenkins_job_capacity_snapshots"

    id = Column(Integer, primary_key=True, index=True)

    provider = Column(String, nullable=False, default="JENKINS")
    snapshot_type = Column(String, nullable=False, default="jenkins_job_capacity")

    job_name = Column(String, nullable=False, index=True)
    build_number = Column(Integer, nullable=True, index=True)

    result = Column(String, nullable=True, index=True)
    status = Column(String, nullable=True)

    built_on = Column(String, nullable=True, index=True)
    duration_seconds = Column(Float, nullable=True)
    estimated_duration_seconds = Column(Float, nullable=True)
    queue_seconds = Column(Float, nullable=True)

    timestamp_start = Column(DateTime(timezone=True), nullable=True)
    timestamp_end = Column(DateTime(timezone=True), nullable=True)

    build_url = Column(String, nullable=True)
    is_building = Column(String, nullable=True)
    raw_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)