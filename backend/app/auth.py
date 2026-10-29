"""Back-office accounts: email and password, and the sessions they open.

By default anyone who can open the back office can create an account and
use it at once. With `MEDORA_REGISTRATION_OPEN=false` only the first account
works straight away; later ones wait for an approval (`PATCH
/api/admin/users/{id}`).

Passwords are stored as scrypt hashes; session tokens as SHA-256 hashes, so
a copy of the database gives access to neither.
"""

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AdminSession, AdminUser

SESSION_HOURS = 12
MIN_PASSWORD = 8
# After this many wrong passwords for one email, sign-in pauses.
MAX_FAILURES = 5
LOCK_SECONDS = 60

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
_failures: dict[str, tuple[int, float]] = {}


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    except ValueError:
        return False
    return hmac.compare_digest(actual.hex(), digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register(db: Session, email: str, name: str, password: str, open_to_all: bool = True) -> AdminUser:
    email = normalize_email(email)
    if "@" not in email or "." not in email.split("@")[-1] or " " in email:
        raise AuthError("Enter a valid email address", 422)
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"The password needs at least {MIN_PASSWORD} characters", 422)
    if db.scalar(select(AdminUser).where(AdminUser.email == email)) is not None:
        raise AuthError("An account with this email already exists", 409)
    first = db.scalar(select(func.count()).select_from(AdminUser)) == 0
    user = AdminUser(
        email=email,
        name=name.strip() or email.split("@")[0],
        password_hash=hash_password(password),
        # With registration closed, later accounts wait for an approval.
        approved=first or open_to_all,
    )
    db.add(user)
    db.commit()
    return user


def sign_in(db: Session, email: str, password: str) -> tuple[AdminUser, str]:
    """The user and a new session token. Raises AuthError otherwise."""
    email = normalize_email(email)
    count, since = _failures.get(email, (0, 0.0))
    if count >= MAX_FAILURES and time.monotonic() - since < LOCK_SECONDS:
        raise AuthError("Too many attempts. Wait a minute and try again.", 429)

    user = db.scalar(select(AdminUser).where(AdminUser.email == email))
    # The same answer for an unknown email and a wrong password.
    if user is None or not verify_password(password, user.password_hash):
        _failures[email] = (count + 1 if time.monotonic() - since < LOCK_SECONDS else 1, time.monotonic())
        raise AuthError("Wrong email or password")
    _failures.pop(email, None)
    if not user.approved:
        raise AuthError("This account is waiting for approval by an administrator", 403)
    if not user.active:
        raise AuthError("This account has been switched off", 403)

    user.last_login_at = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    db.add(
        AdminSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS),
        )
    )
    db.commit()
    return user, token


def user_for_token(db: Session, token: str) -> AdminUser | None:
    """The signed-in user a token belongs to, if it is still valid."""
    if not token:
        return None
    session = db.get(AdminSession, _token_hash(token))
    if session is None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:  # SQLite returns naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        return None
    user = db.get(AdminUser, session.user_id)
    return user if user is not None and user.active and user.approved else None


def sign_out(db: Session, token: str) -> None:
    session = db.get(AdminSession, _token_hash(token))
    if session is not None:
        db.delete(session)
        db.commit()


def end_sessions(db: Session, user_id: str) -> None:
    """Signs a user out everywhere, for when the account is switched off."""
    for session in db.scalars(select(AdminSession).where(AdminSession.user_id == user_id)):
        db.delete(session)
