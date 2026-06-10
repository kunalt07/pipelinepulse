"""Runtime-overridable settings.

Resolution order: DB → env var (uppercased key) → default.

A 5-second TTL cache keeps high-frequency call sites cheap; the cache is
invalidated on every set/clear so UI changes propagate within a few seconds.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional

from database import SessionLocal
from models import Setting

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "webhook_url": None,
    "gemini_api_key": None,
    "gemini_model": "gemini-flash-lite-latest",
    "sync_interval_minutes": 2,
    "stuck_multiplier": 2.0,
    "stuck_floor_seconds": 60.0,
    "stuck_min_history": 5,
}

# Settings that map to existing env vars — env wins over default but loses to DB.
ENV_KEYS: dict[str, str] = {
    "webhook_url": "WEBHOOK_URL",
    "gemini_api_key": "GEMINI_API_KEY",
    "gemini_model": "GEMINI_MODEL",
}

SECRET_KEYS = {"webhook_url", "gemini_api_key"}

CACHE_TTL = 5.0
_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()

# Set by scheduler.start_scheduler() so settings.py can reschedule the sync job
# when sync_interval_minutes changes. None until the scheduler is up.
_scheduler_ref = None


def register_scheduler(scheduler) -> None:
    global _scheduler_ref
    _scheduler_ref = scheduler


def _read_db(key: str) -> Optional[str]:
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row else None
    finally:
        db.close()


def _coerce(raw: Optional[str], cast: Optional[Callable], default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if cast is None:
        return raw
    try:
        return cast(raw)
    except (TypeError, ValueError):
        logger.warning(f"Could not cast setting value {raw!r} via {cast}; using default {default!r}")
        return default


def get_setting(key: str, cast: Optional[Callable] = None) -> Any:
    """DB → env → default. Returns Python type when `cast` is given (int/float/bool)."""
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")

    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and (now - hit[0] < CACHE_TTL):
            return hit[1]

    db_val = _read_db(key)
    if db_val is not None and db_val != "":
        resolved = _coerce(db_val, cast, DEFAULTS[key])
    else:
        env_var = ENV_KEYS.get(key)
        env_val = (os.getenv(env_var) or "").strip() if env_var else ""
        if env_val:
            resolved = _coerce(env_val, cast, DEFAULTS[key])
        else:
            resolved = DEFAULTS[key]

    with _lock:
        _cache[key] = (now, resolved)
    return resolved


def set_setting(key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == key).first()
        as_str = "" if value is None else str(value)
        if row is None:
            row = Setting(key=key, value=as_str)
            db.add(row)
        else:
            row.value = as_str
        db.commit()
    finally:
        db.close()
    _invalidate(key)
    _on_change(key)


def clear_setting(key: str) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")
    db = SessionLocal()
    try:
        db.query(Setting).filter(Setting.key == key).delete()
        db.commit()
    finally:
        db.close()
    _invalidate(key)
    _on_change(key)


def is_set(key: str) -> bool:
    """True if the setting has *any* non-empty value (DB or env). Used for masked display."""
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")
    db_val = _read_db(key)
    if db_val:
        return True
    env_var = ENV_KEYS.get(key)
    if env_var and (os.getenv(env_var) or "").strip():
        return True
    return False


def is_db_set(key: str) -> bool:
    """True only if the DB has an explicit value (so we can show 'overriding env')."""
    val = _read_db(key)
    return bool(val)


def _invalidate(key: str) -> None:
    with _lock:
        _cache.pop(key, None)


def invalidate_all() -> None:
    with _lock:
        _cache.clear()


def _on_change(key: str) -> None:
    """Hook for settings whose change requires runtime action."""
    if key == "sync_interval_minutes" and _scheduler_ref is not None:
        try:
            new_interval = int(get_setting("sync_interval_minutes", cast=int))
            _scheduler_ref.reschedule_job(
                "sync_airflow_data",
                trigger="interval",
                minutes=new_interval,
            )
            logger.info(f"Rescheduled sync_airflow_data to {new_interval} min")
        except Exception as e:
            logger.warning(f"Failed to reschedule sync job: {e}")


# ---------- Convenience accessors used across the codebase ----------

def get_webhook_url() -> Optional[str]:
    val = get_setting("webhook_url")
    return val.strip() if isinstance(val, str) and val.strip() else None


def get_gemini_config() -> tuple[Optional[str], str]:
    """Returns (api_key, model). api_key is None when AI is disabled."""
    key = get_setting("gemini_api_key")
    model = get_setting("gemini_model") or DEFAULTS["gemini_model"]
    if isinstance(key, str) and key.strip():
        return key.strip(), str(model)
    return None, str(model)
