"""Signing in to the back office, and managing who may."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from .. import auth
from ..deps import Admin, CurrentAdmin, Db, admin_token
from ..models import AdminUser
from ..schemas import ApiModel
from ..tenancy import record

router = APIRouter(prefix="/api")


class Credentials(ApiModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class Registration(Credentials):
    name: str = Field(default="", max_length=200)


def _user(user: AdminUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "approved": user.approved,
        "active": user.active,
        "createdAt": user.created_at.isoformat(),
        "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.post("/auth/register", status_code=201)
def register(body: Registration, db: Db, request: Request) -> dict:
    """Creates an account and signs it in. With registration closed, only
    the first account is signed in; later ones wait for an approval."""
    try:
        user = auth.register(
            db, body.email, body.name, body.password, request.app.state.settings.registration_open
        )
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e)) from e
    record(
        request.app.state.engine,
        "account.registered",
        f"{user.email} registered" + ("" if user.approved else " and is waiting for approval"),
        level="info" if user.approved else "warning",
    )
    if not user.approved:
        return {"user": _user(user), "token": None}
    _, token = auth.sign_in(db, body.email, body.password)
    return {"user": _user(user), "token": token}


@router.post("/auth/login")
def login(body: Credentials, db: Db, request: Request) -> dict:
    try:
        user, token = auth.sign_in(db, body.email, body.password)
    except auth.AuthError as e:
        if e.status == 401:
            record(request.app.state.engine, "account.login_failed", f"Failed sign-in for {auth.normalize_email(body.email)[:120]}", level="warning")
        raise HTTPException(e.status, str(e)) from e
    return {"user": _user(user), "token": token}


@router.get("/auth/me")
def me(user: CurrentAdmin) -> dict:
    return _user(user)


@router.post("/auth/logout", status_code=204)
def logout(db: Db, token: str = Depends(admin_token)) -> None:
    auth.sign_out(db, token)


class UserUpdate(ApiModel):
    approved: bool | None = None
    active: bool | None = None


@router.get("/admin/users", dependencies=[Admin])
def list_users(db: Db) -> list[dict]:
    return [_user(u) for u in db.scalars(select(AdminUser).order_by(AdminUser.created_at))]


@router.patch("/admin/users/{user_id}")
def update_user(user_id: str, body: UserUpdate, db: Db, me: CurrentAdmin, request: Request) -> dict:
    user = db.get(AdminUser, user_id)
    if user is None:
        raise HTTPException(404, "Account not found")
    if user.id == me.id and (body.active is False or body.approved is False):
        raise HTTPException(422, "You cannot switch off your own account")
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    if not user.active or not user.approved:
        auth.end_sessions(db, user.id)
    db.commit()
    summary = ", ".join(f"{k}={v}" for k, v in changes.items())
    record(request.app.state.engine, "account.updated", f"{me.email} changed {user.email}: {summary}")
    return _user(user)
