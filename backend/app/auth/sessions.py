"""Session lifecycle: create, resolve, revoke.

Cookie policy:
  httponly  -- JavaScript cannot read the token, so XSS cannot exfiltrate it
  samesite  -- Lax; blocks cross-site POST CSRF while keeping normal links working
  secure    -- on unless INSECURE_COOKIES=true (dev over plain http)
  path=/    -- one session for the whole app
"""

import os
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_token, new_session_token
from app.db.models import AuditLog, User, UserSession, utcnow

COOKIE_NAME = "insite_session"
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "12"))
INSECURE_COOKIES = os.getenv("INSECURE_COOKIES", "").lower() in {"1", "true"}


def create_session(
    db: Session, user: User, user_agent: str | None = None
) -> tuple[UserSession, str]:
    """Issue a new session. Returns (row, raw token) -- raw is never stored."""
    token = new_session_token()
    row = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(hours=SESSION_TTL_HOURS),
        user_agent=(user_agent or "")[:200] or None,
    )
    db.add(row)
    user.last_login_at = utcnow()
    return row, token


def resolve_session(db: Session, token: str | None) -> User | None:
    """Return the live user for a token, or None."""
    if not token:
        return None
    row = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    )
    if row is None or not row.is_valid:
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active or user.is_erased:
        return None
    return user


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    row = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    )
    if row and row.revoked_at is None:
        row.revoked_at = utcnow()


def revoke_all_sessions(db: Session, user: User) -> int:
    """Log the user out everywhere. Used on password change and erasure."""
    count = 0
    for row in user.sessions:
        if row.revoked_at is None:
            row.revoked_at = utcnow()
            count += 1
    return count


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        secure=not INSECURE_COOKIES,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


def read_session_cookie(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def audit(
    db: Session, action: str, user_id: str | None = None, detail: str | None = None
) -> None:
    """Record an action. Never pass personal data in `detail`."""
    db.add(AuditLog(user_id=user_id, action=action, detail=(detail or "")[:500] or None))
