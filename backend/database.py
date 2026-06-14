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

# Tables that gain a user_id column (regular FK) for multi-tenancy.
USER_SCOPED_REGULAR_TABLES = [
    "environments",
    "dag_runs",
    "task_instances",
    "ai_insights",
    "notifications",
    "report_runs",
    "report_schedules",
]

# Tables that get user_id added to their composite PK (alongside env+dag).
USER_SCOPED_PK_TABLES = [
    ("dag_alert_configs", ["environment_id", "dag_id"]),
    ("dag_sla_configs", ["environment_id", "dag_id"]),
    ("run_annotations", ["environment_id", "dag_id", "run_id"]),
]


def run_migrations():
    """Lightweight idempotent migrations. Safe to re-run.

    Order is intentional:
      1. Pre-existing column adds (kept for backwards compat).
      2. Seed the first admin user FROM env vars if users table is empty
         (this used to be at the end; moved up so the default env can be
         owned by admin on a brand-new instance).
      3. Seed the default env (now owned by user 1).
      4. Multi-env migration: environment_id on env-scoped tables.
      5. Multi-tenant migration: user_id on env-scoped tables, backfill to
         user 1, NOT NULL, swap PKs and unique constraints.
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

    # ---------- Auth: seed first admin from AUTH_USER/AUTH_PASS ----------
    _seed_first_user_if_needed()

    # ---------- Multi-env: seed default env ----------
    default_env_id = _ensure_default_env()

    # ---------- Add environment_id to regular tables ----------
    if default_env_id is not None:
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
                "ALTER TABLE dag_runs DROP CONSTRAINT IF EXISTS dag_runs_run_id_key",
                "DROP INDEX IF EXISTS ix_dag_runs_run_id",
                "ALTER TABLE dag_runs ADD CONSTRAINT uq_dag_runs_env_run UNIQUE (environment_id, run_id)",
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
                # NOTE: this old single-column UNIQUE on environment_id will be
                # superseded by uq_report_schedules_user_env in the multi-tenant
                # block below. Drop is handled there.
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_schedules_env ON report_schedules(environment_id)",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    logger.debug(f"migration step skipped: {stmt[:60]}... — {e}")

    # ---------- Multi-tenant migration: user_id on env-scoped tables ----------
    _run_multitenant_migration()

    # ---------- Settings table: owner_user_id for per-user scoping ----------
    _migrate_settings_per_user()


def _run_multitenant_migration() -> None:
    """Add user_id to every env-scoped table. Backfill all existing rows to the
    lowest existing user id (typically the seeded admin = id 1). Idempotent —
    rows that already have user_id set are left alone, and ALTER...SET NOT NULL
    is a no-op on a column that's already NOT NULL.

    If no users exist yet, the migration does nothing — env-scoped tables on a
    brand-new instance are empty anyway, so there's nothing to scope.
    """
    from sqlalchemy import text

    target_user_id = _lowest_user_id()
    if target_user_id is None:
        logger.info(
            "Multi-tenant migration skipped: no users exist yet. Tables are "
            "empty and will get user_id on first row insert."
        )
        return

    with engine.begin() as conn:
        # 1. Regular-FK tables (user_id is NOT NULL but not part of PK).
        for table in USER_SCOPED_REGULAR_TABLES:
            for stmt in [
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id INTEGER",
                f"UPDATE {table} SET user_id = {target_user_id} WHERE user_id IS NULL",
                f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL",
                f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id ON {table}(user_id)",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    logger.debug(f"multitenant migration skipped: {stmt[:60]}... — {e}")

        # 2. environments.name unique constraint: was global, becomes per-user.
        # The old constraint name in PostgreSQL defaults to environments_name_key.
        for stmt in [
            "ALTER TABLE environments DROP CONSTRAINT IF EXISTS environments_name_key",
            "DROP INDEX IF EXISTS ix_environments_name",
            "ALTER TABLE environments ADD CONSTRAINT uq_environments_user_name "
            "UNIQUE (user_id, name)",
            "CREATE INDEX IF NOT EXISTS ix_environments_name ON environments(name)",
        ]:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                logger.debug(f"multitenant migration skipped: {stmt[:60]}... — {e}")

        # 3. Composite-PK tables: user_id added to PK as the leading column.
        for table, old_pk_cols in USER_SCOPED_PK_TABLES:
            old_pk_constraint = f"{table}_pkey"
            new_pk = ", ".join(["user_id"] + old_pk_cols)
            for stmt in [
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id INTEGER",
                f"UPDATE {table} SET user_id = {target_user_id} WHERE user_id IS NULL",
                f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL",
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old_pk_constraint}",
                f"ALTER TABLE {table} ADD PRIMARY KEY ({new_pk})",
                f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id ON {table}(user_id)",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    logger.debug(f"multitenant migration skipped: {stmt[:60]}... — {e}")

        # 4. report_schedules unique constraint: was per-env, becomes per (user, env).
        for stmt in [
            "DROP INDEX IF EXISTS uq_report_schedules_env",
            "ALTER TABLE report_schedules DROP CONSTRAINT IF EXISTS uq_report_schedules_env",
            "ALTER TABLE report_schedules ADD CONSTRAINT uq_report_schedules_user_env "
            "UNIQUE (user_id, environment_id)",
        ]:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                logger.debug(f"multitenant migration skipped: {stmt[:60]}... — {e}")

    logger.info(f"Multi-tenant migration: backfilled all rows to user_id={target_user_id}")


# Settings keys that move per-user (Session 3). All others stay global with
# owner_user_id = 0 sentinel.
PER_USER_SETTING_KEYS = {
    "webhook_url",
    "gemini_api_key",
    "gemini_model",
    "sync_interval_minutes",
}


def _migrate_settings_per_user() -> None:
    """Add owner_user_id to settings table; backfill existing per-user-scoped
    keys to user 1 (the admin); leave global keys with owner_user_id = 0.

    Also seeds admin's per-user rows from the legacy AUTH_USER/AUTH_PASS-style
    env vars (WEBHOOK_URL, GEMINI_API_KEY) so admin's pre-tenancy setup keeps
    working. New users won't inherit these values — get_setting's per-user
    rule blocks env-var fallback for non-global lookups.

    Idempotent. Re-running on an already-migrated DB is a no-op for the column
    add; UPDATEs only touch rows still NULL; seeding skips rows that already exist.
    """
    from sqlalchemy import text
    from datetime import datetime as _dt

    target_user_id = _lowest_user_id()

    with engine.begin() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS owner_user_id INTEGER"
            ))
        except Exception as e:
            logger.debug(f"settings owner_user_id add skipped: {e}")

        # Backfill: per-user keys go to admin (if exists), global keys go to 0.
        if target_user_id is not None:
            keys_csv = ", ".join(f"'{k}'" for k in PER_USER_SETTING_KEYS)
            try:
                conn.execute(text(f"""
                    UPDATE settings SET owner_user_id = {target_user_id}
                    WHERE owner_user_id IS NULL AND key IN ({keys_csv})
                """))
            except Exception as e:
                logger.debug(f"settings per-user backfill skipped: {e}")

        # Anything still NULL becomes global (sentinel = 0).
        try:
            conn.execute(text(
                "UPDATE settings SET owner_user_id = 0 WHERE owner_user_id IS NULL"
            ))
        except Exception as e:
            logger.debug(f"settings global backfill skipped: {e}")

        # Now make it NOT NULL and swap the PK from `key` to `(owner_user_id, key)`.
        for stmt in [
            "ALTER TABLE settings ALTER COLUMN owner_user_id SET NOT NULL",
            "ALTER TABLE settings DROP CONSTRAINT IF EXISTS settings_pkey",
            "ALTER TABLE settings ADD PRIMARY KEY (owner_user_id, key)",
        ]:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                logger.debug(f"settings PK swap skipped: {stmt[:60]}... — {e}")

        # Seed admin's per-user rows from env vars if they're set and admin
        # doesn't already have an explicit row. After this, admin's webhook etc.
        # comes from their per-user row (not the env-var fallback), and new
        # users won't inherit it.
        if target_user_id is not None:
            for setting_key, env_var in [
                ("webhook_url", "WEBHOOK_URL"),
                ("gemini_api_key", "GEMINI_API_KEY"),
                ("gemini_model", "GEMINI_MODEL"),
            ]:
                env_val = (os.getenv(env_var) or "").strip()
                if not env_val:
                    continue
                try:
                    existing = conn.execute(text(
                        "SELECT 1 FROM settings WHERE owner_user_id = :uid AND key = :key"
                    ), {"uid": target_user_id, "key": setting_key}).first()
                    if existing:
                        continue
                    conn.execute(text("""
                        INSERT INTO settings (owner_user_id, key, value, updated_at)
                        VALUES (:uid, :key, :val, :now)
                    """), {
                        "uid": target_user_id,
                        "key": setting_key,
                        "val": env_val,
                        "now": _dt.utcnow(),
                    })
                    logger.info(
                        f"Seeded admin's {setting_key} from {env_var} env var "
                        "(per-user, won't be inherited by new signups)"
                    )
                except Exception as e:
                    logger.debug(f"admin seed for {setting_key} skipped: {e}")


def _lowest_user_id() -> int | None:
    """Returns the lowest user id, or None if zero users exist."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT MIN(id) FROM users")).first()
            if result and result[0] is not None:
                return int(result[0])
    except Exception as e:
        logger.warning(f"_lowest_user_id failed: {e}")
    return None


def _seed_first_user_if_needed() -> None:
    """If no users exist and AUTH_USER/AUTH_PASS env vars are set, create the
    first user (admin) so existing single-instance deployments keep working
    after upgrading to session-based auth."""
    auth_user = (os.getenv("AUTH_USER") or "").strip()
    auth_pass = (os.getenv("AUTH_PASS") or "").strip()
    if not (auth_user and auth_pass):
        return
    try:
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
    """Create the 'default' environment from AIRFLOW_* env vars if no env rows
    exist, owned by the lowest-id user. Returns the id of the default env, or
    None if creation failed (e.g. no users exist yet to own it).

    Idempotent: if any env already exists, returns the is_default one.
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
            result = conn.execute(text(
                "SELECT id FROM environments ORDER BY id LIMIT 1"
            )).first()
            if result:
                env_id = int(result[0])
                conn.execute(text(
                    "UPDATE environments SET is_default = TRUE WHERE id = :id"
                ), {"id": env_id})
                return env_id

            # No env exists. Try to create one — but only if a user exists to own it.
            # Multi-tenant: environments.user_id is NOT NULL after the migration. On
            # brand-new instances the multi-tenant migration hasn't run yet (it
            # depends on at least one user existing), but we still pre-emptively
            # require a user_id here so the same code path works post-migration.
            owner_id = _lowest_user_id()
            if owner_id is None:
                logger.info(
                    "_ensure_default_env: no users yet; skipping default env "
                    "creation. The first-run wizard will create the user's first "
                    "env after they sign up."
                )
                return None

            if not base_url:
                base_url = "http://airflow-webserver:8080"

            # Use a try-with-fallback for the user_id column: pre-multi-tenant
            # schemas don't have it yet, so we attempt the user_id-aware insert
            # first and fall back to the older shape.
            try:
                row = conn.execute(text("""
                    INSERT INTO environments
                      (user_id, name, airflow_base_url, airflow_username,
                       airflow_password, airflow_public_url,
                       is_default, enabled, created_at, updated_at)
                    VALUES
                      (:user_id, 'default', :base_url, :username, :password, :public_url,
                       TRUE, TRUE, NOW(), NOW())
                    RETURNING id
                """), {
                    "user_id": owner_id,
                    "base_url": base_url,
                    "username": username,
                    "password": password,
                    "public_url": public_url,
                }).first()
            except Exception:
                # Pre-multi-tenant schema (column doesn't exist yet). Fall back.
                row = conn.execute(text("""
                    INSERT INTO environments
                      (name, airflow_base_url, airflow_username,
                       airflow_password, airflow_public_url,
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
