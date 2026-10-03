"""Workspace users, teams and the sharing directory."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_user, require_role
from app.core.database import get_db
from app.core.security import hash_password
from app.models import Team, TeamMember, User, uid, utcnow
from app.schemas import AddTeamMember, TeamCreate, TeamUpdate, UserCreate, UserUpdate
from app.services.audit import activity
from app.services.records import me_record, record

router = APIRouter()


@router.get("/api/users")
def users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    query = select(User).where(User.workspace_id == user.workspace_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    size = min(per_page, 200)
    results = db.scalars(query.order_by(User.name).offset((page - 1) * size).limit(size)).all()
    return {"items": [me_record(u) for u in results], "total": total}


@router.post("/api/users")
def create_user(body: UserCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    """Create an account in the admin's workspace; the only way to add people when self-service sign-up is off."""
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(409, "An account with this email already exists")
    created = User(
        id=uid(),
        workspace_id=user.workspace_id,
        name=body.name.strip(),
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(created)
    activity(db, user, "user.created", "user", created.id, role=body.role)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from None
    return me_record(created)


@router.patch("/api/users/{user_id}")
def update_user(
    user_id: str, body: UserUpdate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))
):
    target = db.get(User, user_id)
    if not target or target.workspace_id != user.workspace_id:
        raise HTTPException(404, "User not found")
    if target.id == user.id and body.role and body.role != "admin":
        raise HTTPException(409, "You cannot remove your own administrator role")
    if target.id == user.id and body.active is False:
        raise HTTPException(409, "You cannot deactivate your own account")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(target, key, value)
    activity(db, user, "user.updated", "user", target.id)
    db.commit()
    return me_record(target)


@router.get("/api/teams")
def teams(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    query = select(Team).where(Team.workspace_id == user.workspace_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    size = min(per_page, 200)
    items = db.scalars(query.order_by(Team.name).offset((page - 1) * size).limit(size)).all()
    result = []
    for team in items:
        item = record(team)
        item["members"] = [
            me_record(db.get(User, m.user_id))
            for m in db.scalars(select(TeamMember).where(TeamMember.team_id == team.id)).all()
        ]
        if user.role not in ("admin", "manager"):
            # Match /api/directory: only admins and managers see member email addresses.
            item["members"] = [{**member, "email": None} for member in item["members"]]
        result.append(item)
    return {"items": result, "total": total}


@router.post("/api/teams")
def create_team(
    body: TeamCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))
):
    team = Team(
        id=uid(),
        workspace_id=user.workspace_id,
        name=body.name.strip(),
        description=body.description,
        created_at=utcnow(),
    )
    db.add(team)
    activity(db, user, "team.created", "team", team.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A team with that name already exists") from None
    return record(team)


@router.patch("/api/teams/{team_id}")
def update_team(
    team_id: str,
    body: TeamUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "manager")),
):
    team = db.get(Team, team_id)
    if not team or team.workspace_id != user.workspace_id:
        raise HTTPException(404, "Team not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(team, key, value)
    db.commit()
    return record(team)


@router.delete("/api/teams/{team_id}", status_code=204)
def delete_team(team_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))):
    team = db.get(Team, team_id)
    if not team or team.workspace_id != user.workspace_id:
        raise HTTPException(404, "Team not found")
    db.delete(team)
    db.commit()


@router.post("/api/teams/{team_id}/members")
def add_team_member(
    team_id: str,
    body: AddTeamMember,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "manager")),
):
    team, target = db.get(Team, team_id), db.get(User, body.user_id)
    if not team or team.workspace_id != user.workspace_id or not target or target.workspace_id != user.workspace_id:
        raise HTTPException(404, "Team or user not found")
    if not db.scalar(select(TeamMember.id).where(TeamMember.team_id == team.id, TeamMember.user_id == target.id)):
        db.add(TeamMember(team_id=team.id, user_id=target.id))
        db.commit()
    return {"team_id": team.id, "user_id": target.id}


@router.delete("/api/teams/{team_id}/members/{user_id}", status_code=204)
def remove_team_member(
    team_id: str, user_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))
):
    team = db.get(Team, team_id)
    if not team or team.workspace_id != user.workspace_id:
        raise HTTPException(404, "Team not found")
    member = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id))
    if member:
        db.delete(member)
        db.commit()


@router.get("/api/directory")
def share_directory(
    q: str = "", limit: int = 20, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))
):
    needle = q.strip().lower()
    limit = min(max(limit, 1), 50)
    users_query = select(User).where(User.workspace_id == user.workspace_id, User.active.is_(True))
    teams_query = select(Team).where(Team.workspace_id == user.workspace_id)
    if needle:
        pattern = f"%{needle}%"
        users_query = users_query.where(or_(func.lower(User.name).like(pattern), func.lower(User.email).like(pattern)))
        teams_query = teams_query.where(func.lower(Team.name).like(pattern))
    users_out = [
        {"id": row.id, "name": row.name, "email": row.email}
        for row in db.scalars(users_query.order_by(User.name).limit(limit)).all()
    ]
    teams_out = [
        {"id": row.id, "name": row.name} for row in db.scalars(teams_query.order_by(Team.name).limit(limit)).all()
    ]
    return {"users": users_out, "teams": teams_out}
