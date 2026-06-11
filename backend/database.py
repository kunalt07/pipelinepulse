from sqlalchemy import create_engine, Column, String, DateTime, Float, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging
import os

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Tables that get an environment_id column (regular FK, not part of PK)
ENV_SCOPED_REGULAR_TABLES = [
    "dag_runs",
    "task_instances",
    "ai_insights",
    "notifications",
    "report_runs",
]

# Tables where environment_id participates in the primary key — needs PK swap
ENV_SCOPED_PK_TABLES = [
    # (table, existing pk columns)
    ("dag_alert_configs", ["dag_id"]),
    ("dag_sla_configs", ["dag_id"]),
    ("run_annotations", ["dag_id", "run_id"]),
]


def run_migrations():
    """Lightweight idempotent migrations. Safe to re-run.

    Multi-environment migration (Phase 3 #5):
      1. Pre-existing column adds (kept for backwards compat).
      2. Seed `environments` table with a default env from AIRFLOW_* env vars
         if no rows exist.
      3. Add `environment_id` to env-scoped historical tables, backfill to
         the default env, then NOT NULL it.
      4. Swap PKs on dag_alert_configs / dag_sla_configs / run_annotations
         to include environment_id.
      5. Replace dag_runs.run_id UNIQUE constraint with a (env_id, run_id) one.
      6. Migrate report_schedules from a singleton row (id=1) to one row per env.
    """
    from sqlalchemy import text

    pre_env_statements = [
        "ALTER TABLE task_instances ADD COLUMN IF NOT EXISTS try_number INTEGER",
        "ALTER TABLE report_runs ADD COLUMN IF NOT EXISTS summary_line VARCHAR",
        "ALTER TABLE report_runs ADD COLUMN IF NOT EXISTS delivered VARCHAR",
        "ALTER TABLE report_runs ADD COLUMN IF NOT EXISTS webhook_url VARCHAR",
        "ALTER TABLE report_schedules ADD COLUMN IF NOT EXISTS webhook_url VARCHAR",
    ]

    with engine.begin() as conn:
        for stmt in pre_env_statements:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass

    # ---------- Multi-env: seed default env ----------
    default_env_id = _ensure_default_env()
    if default_env_id is None:
        logger.warning("Could not seed default environment; multi-env migration skipped")
        return

    # ---------- Add environment_id to regular tables ----------
    with engine.begin() as conn:
        for table in ENV_SCOPED_REGULAR_TABLES:
            for stmt in [
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS environment_id INTEGER",
                f"UPDATE {table} SET environment_id = {default_env_id} WHERE environment_id IS NULL",
                f"ALTER TABLE {table} ALTER COLUMN environment_id SET NOT NULL",
                f"CREATE INDEX IF NOT EXISTS ix_{table}_environment_id ON {table}(environment_id)",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    logger.debug(f"migration step skipped: {stmt[:60]}... — {e}")

        # Replace dag_runs.run_id global UNIQUE with (env_id, run_id) UNIQUE.
        for stmt in [
            # Drop the old UNIQUE on run_id alone. SQLAlchemy's create_all named it
            # with table-derived prefix; we try both common shapes.
            "ALTER TABLE dag_runs DROP CONSTRAINT IF EXISTS dag_runs_run_id_key",
            "DROP INDEX IF EXISTS ix_dag_runs_run_id",
            # Add the composite UNIQUE if not already there.
            "ALTER TABLE dag_runs ADD CONSTRAINT uq_dag_runs_env_run UNIQUE (environment_id, run_id)",
            # Re-create non-unique run_id index for query performance.
            "CREATE INDEX IF NOT EXISTS ix_dag_runs_run_id ON dag_runs(run_id)",
        ]:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                logger.debug(f"migration step skipped: {stmt[:60]}... — {e}")

    # ---------- Add environment_id + swap PK on config tables ----------
    with engine.begin() as conn:
        for table, old_pk_cols in ENV_SCOPED_PK_TABLES:
            old_pk_constraint = f"{table}_pkey"
            for stmt in [
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS environment_id INTEGER",
                f"UPDATE {table} SET environment_id = {default_env_id} WHERE environment_id IS NULL",
                f"ALTER TABLE {table} ALTER COLUMN environment_id SET NOT NULL",
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old_pk_constraint}",
                f"ALTER TABLE {table} ADD PRIMARY KEY (environment_id, {', '.join(old_pk_cols)})",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    logger.debug(f"migration step skipped: {stmt[:60]}... — {e}")

    # ---------- Migrate report_schedules to per-env ----------
    with engine.begin() as conn:
        for stmt in [
            "ALTER TABLE report_schedules ADD COLUMN IF NOT EXISTS environment_id INTEGER",
            f"UPDATE report_schedules SET environment_id = {default_env_id} WHERE environment_id IS NULL",
            "ALTER TABLE report_schedules ALTER COLUMN environment_id SET NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_schedules_env ON report_schedules(environment_id)",
        ]:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                logger.debug(f"migration step skipped: {stmt[:60]}... — {e}")

    # ---------- Auth: seed first user from AUTH_USER/AUTH_PASS if empty ----------
    _seed_first_user_if_needed()


def _seed_first_user_if_needed() -> None:
    """If no users exist and AUTH_USER/AUTH_PASS env vars are set, create the
    first user (admin) so existing single-instance deployments keep working
    after upgrading to session-based auth."""
    auth_user = (os.getenv("AUTH_USER") or "").strip()
    auth_pass = (os.getenv("AUTH_PASS") or "").strip()
    if not (auth_user and auth_pass):
        return
    try:
        # Lazy imports to avoid circular dependencies at module load.
        from sqlalchemy import text as _text
        from auth import hash_password
        from datetime import datetime as _dt
        with engine.begin() as conn:
            existing = conn.execute(_text("SELECT COUNT(*) FROM users")).scalar()
            if existing and int(existing) > 0:
                return
            email = auth_user if "@" in auth_user else f"{auth_user}@local"
            conn.execute(_text("""
                INSERT INTO users (email, password_hash, name, is_admin, created_at)
                VALUES (:email, :hash, :name, TRUE, :now)
            """), {
                "email": email,
                "hash": hash_password(auth_pass),
                "name": auth_user,
                "now": _dt.utcnow(),
            })
        logger.info(
            f"Seeded first admin user from AUTH_USER/AUTH_PASS env vars "
            f"(email='{email}'). You can now sign in via the web UI."
        )
    except Exception as e:
        logger.warning(f"_seed_first_user_if_needed failed: {e}")


def _ensure_default_env() -> int | None:
    """Create the 'default' environment from AIRFLOW_* env vars if no env rows exist.

    Returns the id of the default environment, or None if creation failed.
    Idempotent: if any env already exists, returns the is_default one (or the lowest id).
    """
    from sqlalchemy import text
    base_url = (os.getenv("AIRFLOW_BASE_URL") or "").strip()
    username = (os.getenv("AIRFLOW_USERNAME") or "").strip() or None
    password = (os.getenv("AIRFLOW_PASSWORD") or "").strip() or None
    public_url = (os.getenv("AIRFLOW_PUBLIC_URL") or "").strip() or None

    try:
        with engine.begin() as conn:
            result = conn.execute(text(
                "SELECT id FROM environments WHERE is_default = TRUE ORDER BY id LIMIT 1"
            )).first()
            if result:
                return int(result[0])
            # No default — try to find any env first
            result = conn.execute(text(
                "SELECT id FROM environments ORDER BY id LIMIT 1"
            )).first()
            if result:
                # Promote it to default
                env_id = int(result[0])
                conn.execute(text(
                    "UPDATE environments SET is_default = TRUE WHERE id = :id"
                ), {"id": env_id})
                return env_id
            # No env at all — create one from env vars
            if not base_url:
                # No env vars set either; create a placeholder so migrations can still proceed.
                # The user will edit it via the UI.
                base_url = "http://airflow-webserver:8080"
            row = conn.execute(text("""
                INSERT INTO environments
                  (name, airflow_base_url, airflow_username, airflow_password, airflow_public_url,
                   is_default, enabled, created_at, updated_at)
                VALUES
                  ('default', :base_url, :username, :password, :public_url,
                   TRUE, TRUE, NOW(), NOW())
                RETURNING id
            """), {
                "base_url": base_url,
                "username": username,
                "password": password,
                "public_url": public_url,
            }).first()
            return int(row[0]) if row else None
    except Exception as e:
        logger.warning(f"_ensure_default_env failed: {e}")
        return None
