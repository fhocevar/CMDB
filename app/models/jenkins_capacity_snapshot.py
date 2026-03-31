from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func

from app.core.database import Base


class JenkinsCapacitySnapshot(Base):
    __tablename__ = "jenkins_capacity_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False, default="JENKINS")
    snapshot_type = Column(String, nullable=False, default="jenkins_capacity")

    overall_status = Column(String, nullable=True)

    agents_total = Column(Integer, nullable=True)
    agents_online = Column(Integer, nullable=True)
    agents_offline = Column(Integer, nullable=True)
    agents_temp_offline = Column(Integer, nullable=True)

    executors_total = Column(Integer, nullable=True)
    executors_busy = Column(Integer, nullable=True)
    executors_idle = Column(Integer, nullable=True)

    queue_total = Column(Integer, nullable=True)
    queue_buildable = Column(Integer, nullable=True)
    queue_blocked = Column(Integer, nullable=True)
    queue_stuck = Column(Integer, nullable=True)

    executor_usage_percent = Column(Integer, nullable=True)

    avg_cpu_operational_percent = Column(String, nullable=True)
    avg_memory_used_percent = Column(String, nullable=True)
    min_disk_free_gb = Column(String, nullable=True)

    has_real_cpu_data = Column(String, nullable=True)
    has_real_memory_data = Column(String, nullable=True)
    has_real_disk_data = Column(String, nullable=True)

    summary_json = Column(JSON, nullable=True)
    agents_json = Column(JSON, nullable=True)
    limitations_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)