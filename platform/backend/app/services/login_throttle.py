"""Database-backed sign-in throttling per email+client address and per client address, shared by all replicas."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import config
from app.models import LoginAttempt, as_utc, utcnow


def client_address(request: Request) -> str:
    """The peer address; behind a proxy this is the forwarded client only when uvicorn is told to trust it."""
    return request.client.host if request.client else "unknown"


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(("cuautoreview-login", *parts)).encode("utf-8")).hexdigest()


def keys(email: str, address: str) -> tuple[str, str]:
    """Hashed (email+address, address) keys; the email and address themselves are never stored."""
    return _digest("pair", email.strip().lower(), address), _digest("address", address)


def _window_wait(db: Session, column, key: str, limit: int, since: datetime, now: datetime) -> int | None:
    count, oldest = db.execute(
        select(func.count(), func.min(LoginAttempt.created_at)).where(column == key, LoginAttempt.created_at > since)
    ).one()
    if count < limit or oldest is None:
        return None
    reopens = as_utc(oldest) + timedelta(seconds=config.settings.login_window_seconds)
    return max(1, math.ceil((reopens - now).total_seconds()))


def retry_after(db: Session, pair_hash: str, address_hash: str, now: datetime | None = None) -> int | None:
    """Seconds until another attempt is allowed, or None when the caller is not throttled."""
    now = now or utcnow()
    since = now - timedelta(seconds=config.settings.login_window_seconds)
    waits = [
        _window_wait(db, LoginAttempt.pair_hash, pair_hash, config.settings.login_max_failures, since, now),
        _window_wait(db, LoginAttempt.ip_hash, address_hash, config.settings.login_ip_max_failures, since, now),
    ]
    waits = [wait for wait in waits if wait is not None]
    return max(waits) if waits else None


def record_failure(db: Session, pair_hash: str, address_hash: str) -> None:
    db.add(LoginAttempt(pair_hash=pair_hash, ip_hash=address_hash))


def clear(db: Session, pair_hash: str) -> None:
    """A successful sign-in resets that email+address counter; the address-wide counter keeps aging out."""
    db.execute(
        delete(LoginAttempt).where(LoginAttempt.pair_hash == pair_hash),
        execution_options={"synchronize_session": False},
    )
