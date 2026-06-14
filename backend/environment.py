"""Environment resolution + FastAPI dependency.

Multi-tenant: every environment is owned by a user. Resolution requires both
the user (from the auth dependency) and an optional `?env=` query param.
Cross-tenant access is structurally impossible — a user can't reference
another user's env even by id, because every lookup filters by `user_id`
first.

`?env=` accepts:
  - missing  → user's default environment (or first env)
  - integer  → environment id (still filtered by user_id)
  - string   → environment name within the user's envs
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models import Environment, User
from auth import current_user


def _resolve_for_user(
    db: Session, user: User, env_param: Optional[str]
) -> Optional[Environment]:
    base = db.query(Environment).filter(Environment.user_id == user.id)

    if env_param is None or env_param == "":
        env = base.filter(Environment.is_default.is_(True)).first()
        if env is not None:
            return env
        return base.order_by(Environment.id.asc()).first()

    # Try integer id first — but still gated by user_id.
    try:
        env_id = int(env_param)
        env = base.filter(Environment.id == env_id).first()
        if env is not None:
            return env
    except (TypeError, ValueError):
        pass

    return base.filter(Environment.name == env_param).first()


def get_user_env(db: Session, user: User, env_param: Optional[str]) -> Environment:
    """Resolve an env for a specific user, raising 404 if missing.

    Used by the FastAPI dependency below and by anywhere that needs to look up
    an env in a tenant-scoped way.
    """
    env = _resolve_for_user(db, user, env_param)
    if env is None:
        raise HTTPException(
            status_code=404,
            detail=f"Environment not found: {env_param or '(default)'}",
        )
    return env


def list_user_environments(
    db: Session, user: User, enabled_only: bool = False
) -> list[Environment]:
    """All of a single user's envs."""
    q = db.query(Environment).filter(Environment.user_id == user.id)
    if enabled_only:
        q = q.filter(Environment.enabled.is_(True))
    return q.order_by(Environment.id.asc()).all()


def list_all_environments(
    db: Session, enabled_only: bool = False
) -> list[Environment]:
    """All envs across all users. ONLY for non-HTTP contexts (scheduler jobs)
    that legitimately need to iterate over every tenant.

    Never call this from a request handler — use list_user_environments()."""
    q = db.query(Environment)
    if enabled_only:
        q = q.filter(Environment.enabled.is_(True))
    return q.order_by(Environment.user_id.asc(), Environment.id.asc()).all()


def env_dep(
    env: Optional[str] = None,
    user: Optional[User] = Depends(current_user),
    db: Session = Depends(get_db),
) -> Environment:
    """FastAPI dependency: returns the active Environment for the current user.

    Raises 401 if not signed in, 404 if env can't be resolved within the user's
    tenant. Endpoints that depend on this transitively require auth.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return get_user_env(db, user, env)


# Standalone helper for non-HTTP contexts (scheduler jobs, CLI utilities).
def list_all_envs_standalone(enabled_only: bool = True) -> list[Environment]:
    db = SessionLocal()
    try:
        return list_all_environments(db, enabled_only=enabled_only)
    finally:
        db.close()
