"""Hospital accounts, sessions, and the audit trail.

Password and token handling reuse `app.auth` (scrypt hashes, SHA-256 token
hashes), but against the hospital tables, so hospital and company accounts
never mix.
"""

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..deps import get_db
from ..models import Tenant
from .models import ROLES, AuditEntry, HospitalSession, HospitalUser

SESSION_HOURS = 12


class HospitalError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def temporary_password() -> str:
    """Easy to read out and type: no 0/O or 1/l."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def _check_email(db: Session, email: str, ignore_id: str | None = None) -> str:
    email = auth.normalize_email(email)
    if "@" not in email or "." not in email.split("@")[-1] or " " in email:
        raise HospitalError("Enter a valid email address")
    taken = db.scalar(select(HospitalUser).where(HospitalUser.email == email))
    if taken is not None and taken.id != ignore_id:
        raise HospitalError("An account with this email already exists", 409)
    return email


def create_user(
    db: Session,
    tenant_id: str,
    *,
    email: str,
    name: str,
    role: str,
    password: str | None = None,
    chosen: bool = False,
    **profile,
) -> tuple[HospitalUser, str]:
    """A new account and its password: a temporary one (shown once, changed
    at first sign-in) unless the company chose it (`chosen`)."""
    if role not in ROLES:
        raise HospitalError("Unknown role")
    if not name.strip():
        raise HospitalError("Enter a name")
    password = password or temporary_password()
    user = HospitalUser(
        tenant_id=tenant_id,
        email=_check_email(db, email),
        name=name.strip(),
        role=role,
        password_hash=auth.hash_password(password),
        must_change_password=not chosen,
        **profile,
    )
    db.add(user)
    db.flush()
    return user, password


def sign_in(db: Session, email: str, password: str) -> tuple[HospitalUser, str]:
    """The user and a new session token. Raises HospitalError otherwise."""
    email = auth.normalize_email(email)
    key = f"hospital:{email}"  # its own counter, beside the company sign-ins
    count, since = auth._failures.get(key, (0, 0.0))
    if count >= auth.MAX_FAILURES and time.monotonic() - since < auth.LOCK_SECONDS:
        raise HospitalError("Too many attempts. Wait a minute and try again.", 429)
    user = db.scalar(select(HospitalUser).where(HospitalUser.email == email))
    if user is None or not auth.verify_password(password, user.password_hash):
        auth._failures[key] = (
            count + 1 if time.monotonic() - since < auth.LOCK_SECONDS else 1,
            time.monotonic(),
        )
        raise HospitalError("Wrong email or password", 401)
    auth._failures.pop(key, None)
    if not user.active:
        raise HospitalError("This account has been switched off. Ask your hospital's administrator.", 403)
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.active:
        raise HospitalError("This hospital's account is switched off.", 403)
    user.last_login_at = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    db.add(
        HospitalSession(
            token_hash=auth._token_hash(token),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS),
        )
    )
    db.commit()
    return user, token


def user_for_token(db: Session, token: str) -> HospitalUser | None:
    if not token:
        return None
    session = db.get(HospitalSession, auth._token_hash(token))
    if session is None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:  # SQLite returns naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        return None
    user = db.get(HospitalUser, session.user_id)
    if user is None or not user.active:
        return None
    tenant = db.get(Tenant, user.tenant_id)
    return user if tenant is not None and tenant.active else None


def sign_out(db: Session, token: str) -> None:
    session = db.get(HospitalSession, auth._token_hash(token))
    if session is not None:
        db.delete(session)
        db.commit()


def end_sessions(db: Session, user_id: str) -> None:
    for session in db.scalars(select(HospitalSession).where(HospitalSession.user_id == user_id)):
        db.delete(session)


def set_password(db: Session, user: HospitalUser, current: str, new: str) -> None:
    if not auth.verify_password(current, user.password_hash):
        raise HospitalError("The current password is wrong", 403)
    if len(new) < auth.MIN_PASSWORD:
        raise HospitalError(f"The new password needs at least {auth.MIN_PASSWORD} characters")
    if new == current:
        raise HospitalError("Choose a password different from the temporary one")
    user.password_hash = auth.hash_password(new)
    user.must_change_password = False
    db.commit()


def audit(db: Session, user: HospitalUser, action: str, detail: str = "") -> None:
    """One line in the hospital's audit trail, in the caller's transaction."""
    db.add(
        AuditEntry(
            tenant_id=user.tenant_id,
            user_id=user.id,
            user_name=user.name,
            role=user.role,
            action=action,
            detail=detail[:2000],
        )
    )


# --- request dependencies -------------------------------------------------------


def hospital_token(
    x_hospital_token: Annotated[str, Header()] = "",
    authorization: Annotated[str, Header()] = "",
) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_hospital_token


def signed_in(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Depends(hospital_token)],
) -> HospitalUser:
    """Anyone signed in at a hospital."""
    user = user_for_token(db, token)
    if user is None:
        raise HTTPException(401, "Sign in to your hospital account")
    request.state.hospital_user = user
    return user


def hospital_admin(user: Annotated[HospitalUser, Depends(signed_in)]) -> HospitalUser:
    """A hospital admin: the only role with the hospital portal."""
    if user.role != "hospital_admin":
        raise HTTPException(403, "Only the hospital's administrators can open this page")
    return user


Signed = Annotated[HospitalUser, Depends(signed_in)]
HospitalAdmin = Annotated[HospitalUser, Depends(hospital_admin)]
