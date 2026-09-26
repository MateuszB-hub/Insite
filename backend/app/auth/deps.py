"""FastAPI dependencies for authentication."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.sessions import read_session_cookie, resolve_session
from app.db.base import get_db
from app.db.models import User

DbSession = Annotated[Session, Depends(get_db)]


def current_user_optional(request: Request, db: DbSession) -> User | None:
    return resolve_session(db, read_session_cookie(request))


def current_user(request: Request, db: DbSession) -> User:
    """Require a logged-in user. 401 otherwise."""
    user = resolve_session(db, read_session_cookie(request))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(current_user_optional)]
