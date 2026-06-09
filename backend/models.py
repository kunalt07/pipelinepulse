from sqlalchemy import Column, String, DateTime, Float, Integer, Text
from database import Base
from datetime import datetime

class DAGRun(Base):
    __tablename__ = "dag_runs"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    dag_id = Column(String, index=True)
    run_id = Column(String, unique=True, index=True)
    state = Column(String)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

class TaskInstance(Base):
    __tablename__ = "task_instances"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    dag_id = Column(String, index=True)
    run_id = Column(String, index=True)
    task_id = Column(String)
    state = Column(String)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    try_number = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

class AIInsight(Base):
    __tablename__ = "ai_insights"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    dag_id = Column(String, index=True)
    run_id = Column(String, index=True)
    insight_type = Column(String)
    content = Column(Text)
    synced_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    dag_id = Column(String, index=True)
    run_id = Column(String, index=True)
    event = Column(String)            # e.g. "run_failed"
    delivered = Column(String)        # "ok" | "skipped" | "error: <reason>"
    webhook_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
