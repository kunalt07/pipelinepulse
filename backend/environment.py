"""Environment resolution + FastAPI dependency.

Endpoints take an optional `?env=` query param:
  - missing  → default environment
  - integer  → environment id
  - string   → environment name (e.g. "prod", "staging")
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models import Environment


def _resolve(db: Session, env_param: Optional[str]) -> Optional[Environment]:
    if env_param is None or env_param == "":
        # Prefer is_default; fall back to lowest id.
        env = db.query(Environment).filter(Environment.is_default.is_(True)).first()
        if env is not None:
            return env
        return db.query(Environment).order_by(Environment.id.asc()).first()

    # Try integer id first
    try:
        env_id = int(env_param)
        env = db.query(Environment).filter(Environment.id == env_id).first()
        if env is not None:
            return env
    except (TypeError, ValueError):
        pass

    return db.query(Environment).filter(Environment.name == env_param).first()


def get_env(db: Session, env_param: Optional[str]) -> Environment:
    """Like _resolve but raises 404 when no env can be resolved."""
    env = _resolve(db, env_param)
    if env is None:
        raise HTTPException(
            status_code=404,
            detail=f"Environment not found: {env_param or '(default)'}",
        )
    return env


def get_default_env(db: Session) -> Environment:
    return get_env(db, None)


def list_environments(db: Session, enabled_only: bool = False) -> list[Environment]:
    q = db.query(Environment)
    if enabled_only:
        q = q.filter(Environment.enabled.is_(True))
    return q.order_by(Environment.id.asc()).all()


def env_dep(env: Optional[str] = None, db: Session = Depends(get_db)) -> Environment:
    """FastAPI dependency: returns the active Environment for the request."""
    return get_env(db, env)


# Standalone helper for non-HTTP contexts (scheduler jobs, CLI utilities).
def list_envs_standalone(enabled_only: bool = True) -> list[Environment]:
    db = SessionLocal()
    try:
        return list_environments(db, enabled_only=enabled_only)
    finally:
        db.close()
