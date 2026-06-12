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
from models import ApiToken, User, UserSession

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "pipelinepulse_session"
SESSION_DURATION = timedelta(days=30)
SESSION_HARD_CAP = timedelta(days=60)

# API tokens use a "pp_" prefix so leaked tokens are easy to grep for in logs.
# Token shape: "pp_" + 64 hex chars (32 random bytes). The token_prefix column
# stores the first 8 chars of plaintext for cheap lookup before bcrypt-verify.
TOKEN_PREFIX = "pp_"
TOKEN_PREFIX_LEN = 8  # how many chars of plaintext we index on (incl. "pp_")

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


# ---------- API tokens ----------

def generate_token() -> str:
    """Returns a fresh plaintext API token, e.g. 'pp_<64 hex chars>'."""
    return f"{TOKEN_PREFIX}{secrets.token_hex(32)}"


def hash_token(plain: str) -> str:
    return _pwd_context.hash(plain)


def create_api_token(db: Session, user: User, name: str) -> tuple[ApiToken, str]:
    """Mint a new token for `user`. Returns (row, plaintext) — plaintext is shown
    once and never persisted."""
    plaintext = generate_token()
    row = ApiToken(
        user_id=user.id,
        name=name.strip()[:100] or "Unnamed token",
        token_prefix=plaintext[:TOKEN_PREFIX_LEN],
        token_hash=hash_token(plaintext),
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, plaintext


def revoke_api_token(db: Session, user: User, token_id: int) -> bool:
    """Soft-delete a token. Returns True if a row was updated, False if not found
    or owned by a different user."""
    row = db.query(ApiToken).filter(
        ApiToken.id == token_id,
        ApiToken.user_id == user.id,
        ApiToken.revoked_at.is_(None),
    ).first()
    if row is None:
        return False
    row.revoked_at = datetime.utcnow()
    db.commit()
    return True


def list_api_tokens(db: Session, user: User) -> list[ApiToken]:
    return (
        db.query(ApiToken)
        .filter(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
        .order_by(ApiToken.created_at.desc())
        .all()
    )


def get_user_from_bearer(db: Session, header_value: Optional[str]) -> Optional[User]:
    """Resolve `Authorization: Bearer pp_<token>` to a User.

    Two-step lookup: first a cheap WHERE on token_prefix (8 chars of hex = ~4B
    distinct values, so almost always 0 or 1 row), then a bcrypt-verify on the
    matched row. None on miss / revoked / bad format.
    """
    if not header_value:
        return None
    parts = header_value.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    plaintext = parts[1].strip()
    if not plaintext.startswith(TOKEN_PREFIX) or len(plaintext) < TOKEN_PREFIX_LEN + 1:
        return None

    prefix = plaintext[:TOKEN_PREFIX_LEN]
    candidates = (
        db.query(ApiToken)
        .filter(ApiToken.token_prefix == prefix, ApiToken.revoked_at.is_(None))
        .all()
    )
    for row in candidates:
        if verify_password(plaintext, row.token_hash):
            row.last_used_at = datetime.utcnow()
            db.commit()
            return db.query(User).filter(User.id == row.user_id).first()
    return None
