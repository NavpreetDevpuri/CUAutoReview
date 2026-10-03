"""FastAPI dependencies for the signed-in user, workspace roles and run access."""

from __future__ import annotations

import threading

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import config
from app.core.database import get_db
from app.core.security import token_digest
from app.models import Batch, User, as_utc, utcnow
from app.models import Session as LoginSession
from app.services.access import get_batch

_signup_lock = threading.Lock()


def get_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw = request.cookies.get(config.settings.session_cookie)
    if not raw:
        raise HTTPException(401, "Sign in required")
    session = db.get(LoginSession, token_digest(raw))
    if not session or as_utc(session.expires_at) <= utcnow():
        raise HTTPException(401, "Session expired")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account inactive")
    request.state.user_id = user.id  # read by the access log
    return user


def signup_transaction_lock(db: Session = Depends(get_db)):
    """Serialize local signup and hold a cross-process PostgreSQL bootstrap lock."""
    _signup_lock.acquire()
    try:
        if db.bind and db.bind.dialect.name == "postgresql":
            from sqlalchemy import text

            db.execute(text("SELECT pg_advisory_xact_lock(53325899261001)"))
        yield
    finally:
        _signup_lock.release()


def require_role(*roles: str):
    def dependency(user: User = Depends(get_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "This action requires " + " or ".join(roles) + " access")
        return user

    return dependency


def require_batch(required_role: str = "viewer"):
    def dependency(
        batch_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)
    ) -> tuple[Batch, User, str]:
        batch, role = get_batch(db, batch_id, user, required_role=required_role)
        return batch, user, role

    return dependency
