from sqlalchemy import Boolean, Column, String, DateTime, Float, Integer, Text
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


class DagAlertConfig(Base):
    __tablename__ = "dag_alert_configs"
    __table_args__ = {'extend_existing': True}

    dag_id = Column(String, primary_key=True)
    muted = Column(Boolean, default=False, nullable=False)
    min_consecutive_failures = Column(Integer, default=1, nullable=False)
    quiet_hours_start = Column(String, nullable=True)   # "HH:MM" or null
    quiet_hours_end = Column(String, nullable=True)     # "HH:MM" or null
    quiet_timezone = Column(String, nullable=True)      # IANA tz, e.g. "America/Los_Angeles"
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReportRun(Base):
    __tablename__ = "report_runs"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    range = Column(String)                       # "7d" | "30d"
    format = Column(String)                      # "md" | "html" | "pdf" — original requested format
    source = Column(String)                      # "manual" | "scheduled"
    summary_line = Column(String, nullable=True) # compact one-liner for history UI
    content_md = Column(Text)                    # canonical Markdown — HTML/PDF re-rendered on demand
    delivered = Column(String, nullable=True)    # "ok" | "skipped" | "error: ..." (scheduled only)
    webhook_url = Column(String, nullable=True)
    generated_at = Column(DateTime, default=datetime.utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = {'extend_existing': True}

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReportSchedule(Base):
    __tablename__ = "report_schedules"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)       # singleton row, id=1
    enabled = Column(Boolean, default=False, nullable=False)
    frequency = Column(String, default="weekly") # "weekly" | "monthly"
    day_of_week = Column(Integer, default=1)     # 0=Mon .. 6=Sun (weekly only)
    day_of_month = Column(Integer, default=1)    # 1..28 (monthly only)
    hour = Column(Integer, default=8)            # 0..23 UTC
    range = Column(String, default="7d")
    format = Column(String, default="html")
    webhook_url = Column(String, nullable=True)  # blank → fall back to global WEBHOOK_URL
    last_sent_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
