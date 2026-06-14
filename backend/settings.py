"""Runtime-overridable settings.

Two scopes:
  - PER_USER keys (webhook_url, gemini_api_key, gemini_model,
    sync_interval_minutes): each user has their own row. `owner_user_id`
    is the sentinel `0` row for the global default; any positive value
    is a user-owned override.
  - GLOBAL keys (stuck_multiplier, stuck_floor_seconds, stuck_min_history):
    one row keyed at `owner_user_id = 0`, applies to all users.

Resolution order for per-user keys:
    user's row → global sentinel row → env var → DEFAULTS

Resolution order for global keys:
    global sentinel row → env var → DEFAULTS

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

GLOBAL_OWNER_ID = 0  # sentinel for "no owner — applies to everyone"

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

# Per-user settings: each user has their own row. Lookup falls back to global
# sentinel row (owner=0) → env var → DEFAULTS.
PER_USER_KEYS = {
    "webhook_url",
    "gemini_api_key",
    "gemini_model",
    "sync_interval_minutes",
}

SECRET_KEYS = {"webhook_url", "gemini_api_key"}

CACHE_TTL = 5.0
# Cache key: (owner_user_id, key). Using user_id=GLOBAL_OWNER_ID for global lookups.
_cache: dict[tuple[int, str], tuple[float, Any]] = {}
_lock = threading.Lock()

# Set by scheduler.start_scheduler() so settings.py can reschedule sync jobs
# when sync_interval_minutes changes. None until the scheduler is up.
_scheduler_ref = None


def register_scheduler(scheduler) -> None:
    global _scheduler_ref
    _scheduler_ref = scheduler


def _scope_for(key: str, user_id: Optional[int]) -> int:
    """Which owner_user_id row to look up for this (key, user) combination."""
    if key in PER_USER_KEYS and user_id is not None and user_id > 0:
        return user_id
    return GLOBAL_OWNER_ID


def _read_db(owner_user_id: int, key: str) -> Optional[str]:
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(
            Setting.owner_user_id == owner_user_id, Setting.key == key
        ).first()
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


def get_setting(
    key: str,
    cast: Optional[Callable] = None,
    user_id: Optional[int] = None,
) -> Any:
    """Resolves a setting value for a user (or globally if user_id is None / 0).

    Per-user keys: tries user row → global sentinel row → env var → default.
    Global keys: tries global sentinel row → env var → default.
    """
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")

    primary_scope = _scope_for(key, user_id)

    now = time.monotonic()
    cache_key = (primary_scope, key)
    with _lock:
        hit = _cache.get(cache_key)
        if hit and (now - hit[0] < CACHE_TTL):
            return hit[1]

    # Resolution rules (different for per-user keys vs global keys):
    #
    # Per-user key (e.g. webhook_url): the user has their OWN setting; we do
    # NOT fall back to a global sentinel or env var if it's not set, because
    # that would mean alice@example.com inherits admin's Discord webhook just
    # by signing up. Per-user keys with no row → DEFAULT (typically None).
    #
    # Global key (e.g. stuck_multiplier): there's only one shared row. Standard
    # DB → env → default fallback chain.
    is_per_user_lookup = primary_scope != GLOBAL_OWNER_ID and key in PER_USER_KEYS

    db_val = _read_db(primary_scope, key)

    if is_per_user_lookup:
        # Strict: only the user's own row counts. No global / env fallback.
        if db_val is not None and db_val != "":
            resolved = _coerce(db_val, cast, DEFAULTS[key])
        else:
            resolved = DEFAULTS[key]
    else:
        # Global lookup: DB row → env var → default.
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
        _cache[cache_key] = (now, resolved)
    return resolved


def set_setting(
    key: str,
    value: Any,
    user_id: Optional[int] = None,
) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")
    scope = _scope_for(key, user_id)

    db = SessionLocal()
    try:
        row = db.query(Setting).filter(
            Setting.owner_user_id == scope, Setting.key == key
        ).first()
        as_str = "" if value is None else str(value)
        if row is None:
            row = Setting(owner_user_id=scope, key=key, value=as_str)
            db.add(row)
        else:
            row.value = as_str
        db.commit()
    finally:
        db.close()
    _invalidate(scope, key)
    _on_change(key, user_id=scope)


def clear_setting(
    key: str,
    user_id: Optional[int] = None,
) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")
    scope = _scope_for(key, user_id)
    db = SessionLocal()
    try:
        db.query(Setting).filter(
            Setting.owner_user_id == scope, Setting.key == key
        ).delete()
        db.commit()
    finally:
        db.close()
    _invalidate(scope, key)
    _on_change(key, user_id=scope)


def is_set(key: str, user_id: Optional[int] = None) -> bool:
    """True if the setting has any value that get_setting would resolve to.

    For per-user keys, only the user's own DB row counts (no global/env fallback).
    For global keys, falls through to env var.
    """
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")
    scope = _scope_for(key, user_id)
    if _read_db(scope, key):
        return True
    is_per_user_lookup = scope != GLOBAL_OWNER_ID and key in PER_USER_KEYS
    if is_per_user_lookup:
        return False
    env_var = ENV_KEYS.get(key)
    if env_var and (os.getenv(env_var) or "").strip():
        return True
    return False


def is_db_set(key: str, user_id: Optional[int] = None) -> bool:
    """True only if the *primary* DB scope has a value (so we can show 'overriding env')."""
    scope = _scope_for(key, user_id)
    return bool(_read_db(scope, key))


def _invalidate(owner_user_id: int, key: str) -> None:
    with _lock:
        _cache.pop((owner_user_id, key), None)


def invalidate_all() -> None:
    with _lock:
        _cache.clear()


def _on_change(key: str, user_id: int = GLOBAL_OWNER_ID) -> None:
    """Hook for settings whose change requires runtime action.

    user_id is the scope where the change was applied (positive = a specific
    user; 0 = global). For sync_interval_minutes, we ask the scheduler to
    reschedule that user's sync job — which the per-user-sync work will
    register.
    """
    if key == "sync_interval_minutes" and _scheduler_ref is not None:
        try:
            new_interval = int(get_setting("sync_interval_minutes", cast=int, user_id=user_id))
            if user_id > 0:
                # Per-user sync job — see scheduler._user_sync_job_id().
                job_id = f"sync_user_{user_id}"
                _scheduler_ref.reschedule_job(
                    job_id, trigger="interval", minutes=new_interval,
                )
                logger.info(f"Rescheduled sync job for user_id={user_id} to {new_interval} min")
            else:
                # Pre-multi-tenant fallback: the legacy single global sync job.
                _scheduler_ref.reschedule_job(
                    "sync_airflow_data", trigger="interval", minutes=new_interval,
                )
                logger.info(f"Rescheduled sync_airflow_data to {new_interval} min")
        except Exception as e:
            logger.warning(f"Failed to reschedule sync job for user {user_id}: {e}")


# ---------- Convenience accessors used across the codebase ----------

def get_webhook_url(user_id: Optional[int] = None) -> Optional[str]:
    val = get_setting("webhook_url", user_id=user_id)
    return val.strip() if isinstance(val, str) and val.strip() else None


def get_gemini_config(user_id: Optional[int] = None) -> tuple[Optional[str], str]:
    """Returns (api_key, model) for the given user (or global if None)."""
    key = get_setting("gemini_api_key", user_id=user_id)
    model = get_setting("gemini_model", user_id=user_id) or DEFAULTS["gemini_model"]
    if isinstance(key, str) and key.strip():
        return key.strip(), str(model)
    return None, str(model)
