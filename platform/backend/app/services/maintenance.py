"""Periodic housekeeping: remove expired sessions and login attempts that no longer affect throttling."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import config
from app.models import LoginAttempt, utcnow
from app.models import Session as LoginSession

BATCH_SIZE = 500
# Housekeeping deletes need no in-memory synchronisation; callers commit straight afterwards.
NO_SYNC = {"synchronize_session": False}


def prune_expired(db: Session, now: datetime | None = None, batch_size: int = BATCH_SIZE) -> dict[str, int]:
    """Delete at most ``batch_size`` rows of each kind so a large backlog never holds long locks."""
    now = now or utcnow()
    sessions = db.scalars(select(LoginSession.token_hash).where(LoginSession.expires_at <= now).limit(batch_size)).all()
    if sessions:
        db.execute(delete(LoginSession).where(LoginSession.token_hash.in_(sessions)), execution_options=NO_SYNC)
    cutoff = now - timedelta(seconds=config.settings.login_window_seconds)
    attempts = db.scalars(select(LoginAttempt.id).where(LoginAttempt.created_at <= cutoff).limit(batch_size)).all()
    if attempts:
        db.execute(delete(LoginAttempt).where(LoginAttempt.id.in_(attempts)), execution_options=NO_SYNC)
    return {"sessions": len(sessions), "login_attempts": len(attempts)}


def prune_user_sessions(db: Session, user_id: str, now: datetime | None = None) -> None:
    """Drop a user's already-expired sessions, e.g. when they sign out."""
    db.execute(
        delete(LoginSession).where(LoginSession.user_id == user_id, LoginSession.expires_at <= (now or utcnow())),
        execution_options=NO_SYNC,
    )
