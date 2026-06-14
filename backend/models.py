from sqlalchemy import (
    Boolean, Column, ForeignKey, Index, Integer, String, DateTime, Float, Text,
    UniqueConstraint,
)
from database import Base
from datetime import datetime


# ---------- Identity ----------


class User(Base):
    __tablename__ = "users"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True)             # 32-byte hex token
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    user_agent = Column(String, nullable=True)


class ApiToken(Base):
    __tablename__ = "api_tokens"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)              # human label
    token_prefix = Column(String, nullable=False, index=True)  # first 8 chars of plaintext
    token_hash = Column(String, nullable=False)         # bcrypt of full plaintext
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)        # soft-delete sentinel


# ---------- Per-user tenant data ----------
#
# Every table below has user_id, scoping the row to its owning tenant. The
# user_id is redundant with environment_id (envs themselves are user-scoped),
# but kept on every row for two reasons:
#   1. Defense in depth — a missing env filter still won't leak across tenants.
#   2. Cross-env queries (e.g. "all my report_runs across all my envs") become
#      single-column lookups.


class Environment(Base):
    __tablename__ = "environments"
    __table_args__ = (
        # Env names are unique per user (was previously globally unique).
        UniqueConstraint("user_id", "name", name="uq_environments_user_name"),
        {'extend_existing': True},
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    airflow_base_url = Column(String, nullable=False)
    airflow_username = Column(String, nullable=True)
    airflow_password = Column(String, nullable=True)   # plaintext (self-hosted trade-off)
    airflow_public_url = Column(String, nullable=True) # webhook deep-links; falls back to base_url
    is_default = Column(Boolean, default=False, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DAGRun(Base):
    __tablename__ = "dag_runs"
    __table_args__ = (
        UniqueConstraint("environment_id", "run_id", name="uq_dag_runs_env_run"),
        Index("ix_dag_runs_env_dag", "environment_id", "dag_id"),
        Index("ix_dag_runs_user_env", "user_id", "environment_id"),
        {'extend_existing': True},
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    dag_id = Column(String, index=True)
    run_id = Column(String, index=True)   # NOT unique alone — globally unique with environment_id
    state = Column(String)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)


class TaskInstance(Base):
    __tablename__ = "task_instances"
    __table_args__ = (
        Index("ix_task_instances_env_run", "environment_id", "run_id"),
        Index("ix_task_instances_env_dag", "environment_id", "dag_id"),
        Index("ix_task_instances_user_env", "user_id", "environment_id"),
        {'extend_existing': True},
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    dag_id = Column(String, index=True)
    run_id = Column(String, index=True)
    insight_type = Column(String)
    content = Column(Text)
    synced_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    dag_id = Column(String, index=True)
    run_id = Column(String, index=True)
    event = Column(String)            # e.g. "run_failed", "sla_deadline_missed"
    delivered = Column(String)        # "ok" | "skipped" | "error: <reason>" | "suppressed:<reason>"
    webhook_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class DagAlertConfig(Base):
    __tablename__ = "dag_alert_configs"
    __table_args__ = {'extend_existing': True}

    # Composite PK: alert config is per-(user, env, dag).
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), primary_key=True)
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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    range = Column(String)                       # "7d" | "30d"
    format = Column(String)                      # "md" | "html" | "pdf" — original requested format
    source = Column(String)                      # "manual" | "scheduled"
    summary_line = Column(String, nullable=True) # compact one-liner for history UI
    content_md = Column(Text)                    # canonical Markdown — HTML/PDF re-rendered on demand
    delivered = Column(String, nullable=True)    # "ok" | "skipped" | "error: ..." (scheduled only)
    webhook_url = Column(String, nullable=True)
    generated_at = Column(DateTime, default=datetime.utcnow, index=True)


class DagSlaConfig(Base):
    __tablename__ = "dag_sla_configs"
    __table_args__ = {'extend_existing': True}

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), primary_key=True)
    dag_id = Column(String, primary_key=True)
    enabled = Column(Boolean, default=True, nullable=False)
    # Daily wall-clock deadline. Both null = no deadline check.
    deadline_time = Column(String, nullable=True)        # "HH:MM"
    deadline_timezone = Column(String, nullable=True)    # IANA tz, e.g. "UTC"
    # Per-run max runtime (seconds). Null = no runtime check.
    max_runtime_seconds = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RunAnnotation(Base):
    __tablename__ = "run_annotations"
    __table_args__ = {'extend_existing': True}

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), primary_key=True)
    dag_id = Column(String, primary_key=True)
    run_id = Column(String, primary_key=True)
    note = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = {'extend_existing': True}

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReportSchedule(Base):
    __tablename__ = "report_schedules"
    __table_args__ = (
        # One schedule per (user, env). A user can have one schedule per env.
        UniqueConstraint("user_id", "environment_id", name="uq_report_schedules_user_env"),
        {'extend_existing': True},
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
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
