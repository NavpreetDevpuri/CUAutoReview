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
from app.services.audit import activity
from app.services.records import me_record
from app.services.seeding import seed_first_workspace

router = APIRouter()


@router.post("/api/auth/signup")
def signup(
    body: Signup, response: Response, db: Session = Depends(get_db), _bootstrap_lock=Depends(signup_transaction_lock)
):
    email = body.email
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    first = db.scalar(select(func.count(User.id))) == 0
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
def login(body: Login, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    password_ok = verify_password(body.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not user.active or not password_ok:
        raise HTTPException(401, "Email or password is incorrect")
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
            db.commit()
    response.delete_cookie(config.settings.session_cookie, path="/")


@router.get("/api/auth/me")
def auth_me(user: User = Depends(get_user)):
    return me_record(user)
