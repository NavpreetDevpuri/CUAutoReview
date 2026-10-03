"""Sign-up, sign-in, sign-out and current-session endpoints."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_user, signup_transaction_lock
from app.core import config
from app.core.database import get_db
from app.core.security import DUMMY_PASSWORD_HASH, hash_password, new_session_token, token_digest, verify_password
from app.models import Session as LoginSession
from app.models import User, Workspace, utcnow
from app.schemas import Login, Signup
from app.services import login_throttle
from app.services.audit import activity
from app.services.maintenance import prune_user_sessions
from app.services.records import me_record
from app.services.seeding import seed_first_workspace

router = APIRouter()

SIGNUP_DISABLED = "Self-service sign-up is disabled. Ask an administrator to create your account."


def _workspace_empty(db: Session) -> bool:
    return db.scalar(select(func.count(User.id))) == 0


@router.get("/api/auth/config")
def auth_config(db: Session = Depends(get_db)):
    """Public sign-in options for the login page; the first account may always be created (bootstrap admin)."""
    return {"signup_enabled": config.settings.allow_signup or _workspace_empty(db)}


@router.post("/api/auth/signup")
def signup(
    body: Signup, response: Response, db: Session = Depends(get_db), _bootstrap_lock=Depends(signup_transaction_lock)
):
    email = body.email
    first = _workspace_empty(db)
    # Checked before the duplicate-email lookup so a disabled sign-up reveals nothing about existing accounts.
    if not first and not config.settings.allow_signup:
        raise HTTPException(403, SIGNUP_DISABLED)
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    workspace = db.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
    if not workspace:
        workspace = Workspace(name="Local workspace")
        db.add(workspace)
        db.flush()
    user = User(
        workspace_id=workspace.id,
        name=body.name.strip(),
        email=email,
        password_hash=hash_password(body.password),
        role="admin" if first else "viewer",
    )
    db.add(user)
    try:
        db.flush()
        if first:
            seed_first_workspace(db, user)
        token = new_session_token()
        db.add(
            LoginSession(
                token_hash=token_digest(token),
                user_id=user.id,
                expires_at=utcnow() + timedelta(hours=config.settings.session_ttl_hours),
            )
        )
        activity(db, user, "auth.signup", "user", user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Account creation conflicted with another signup") from None
    response.set_cookie(
        config.settings.session_cookie,
        token,
        max_age=config.settings.session_ttl_hours * 3600,
        httponly=True,
        secure=config.settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return me_record(user)


@router.post("/api/auth/login")
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    pair_hash, address_hash = login_throttle.keys(email, login_throttle.client_address(request))
    wait = login_throttle.retry_after(db, pair_hash, address_hash)
    if wait:
        raise HTTPException(
            429, "Too many failed sign-in attempts. Try again later.", headers={"Retry-After": str(wait)}
        )
    user = db.scalar(select(User).where(User.email == email))
    password_ok = verify_password(body.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not user.active or not password_ok:
        login_throttle.record_failure(db, pair_hash, address_hash)
        db.commit()
        raise HTTPException(401, "Email or password is incorrect")
    login_throttle.clear(db, pair_hash)
    token = new_session_token()
    db.add(
        LoginSession(
            token_hash=token_digest(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=config.settings.session_ttl_hours),
        )
    )
    activity(db, user, "auth.login", "user", user.id)
    db.commit()
    response.set_cookie(
        config.settings.session_cookie,
        token,
        max_age=config.settings.session_ttl_hours * 3600,
        httponly=True,
        secure=config.settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return me_record(user)


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(config.settings.session_cookie)
    if raw:
        session = db.get(LoginSession, token_digest(raw))
        if session:
            db.delete(session)
            prune_user_sessions(db, session.user_id)
            db.commit()
    response.delete_cookie(config.settings.session_cookie, path="/")


@router.get("/api/auth/me")
def auth_me(user: User = Depends(get_user)):
    return me_record(user)
