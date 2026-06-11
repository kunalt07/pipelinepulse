"""Auth helpers: password hashing, server-side sessions, current_user resolver."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User, UserSession

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "pipelinepulse_session"
SESSION_DURATION = timedelta(days=30)
SESSION_HARD_CAP = timedelta(days=60)

# Bcrypt via passlib; deprecated="auto" lets us roll the hash on next login if we
# ever change rounds.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        return False


def create_session(db: Session, user: User, user_agent: Optional[str] = None) -> str:
    """Create a fresh session for `user`, return the opaque session id."""
    sid = secrets.token_hex(32)
    now = datetime.utcnow()
    sess = UserSession(
        id=sid,
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + SESSION_DURATION,
        user_agent=(user_agent or "")[:500] or None,
    )
    db.add(sess)
    user.last_login_at = now
    db.commit()
    return sid


def get_user_from_session(db: Session, session_id: Optional[str]) -> Optional[User]:
    """Resolve a session id to a User, refreshing last_seen_at + expires_at on the
    way (sliding window, hard-capped at SESSION_HARD_CAP from creation).

    Returns None for missing / expired sessions.
    """
    if not session_id:
        return None
    sess = db.query(UserSession).filter(UserSession.id == session_id).first()
    if sess is None:
        return None
    now = datetime.utcnow()
    if sess.expires_at <= now:
        # Expired — clean it up opportunistically.
        db.delete(sess)
        db.commit()
        return None

    # Slide expiry up to the hard cap from creation.
    new_expiry = min(now + SESSION_DURATION, sess.created_at + SESSION_HARD_CAP)
    if new_expiry > sess.expires_at:
        sess.expires_at = new_expiry
    sess.last_seen_at = now
    db.commit()

    user = db.query(User).filter(User.id == sess.user_id).first()
    return user


def delete_session(db: Session, session_id: str) -> None:
    db.query(UserSession).filter(UserSession.id == session_id).delete()
    db.commit()


def current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Optional dependency — returns None when not logged in.

    During Phase A the API still accepts unauthenticated requests, so endpoints
    that want to gate on a user use this and decide for themselves.
    """
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    return get_user_from_session(db, sid)


def user_count(db: Session) -> int:
    return db.query(User).count()
