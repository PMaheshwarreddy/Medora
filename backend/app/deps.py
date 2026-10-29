from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .auth import user_for_token
from .offline import UNREACHABLE
from .models import AdminUser, Tenant
from .settings import Settings
from .tenancy import find_api_key, find_tenant


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def admin_token(
    x_admin_key: Annotated[str, Header()] = "",
    authorization: Annotated[str, Header()] = "",
) -> str:
    """The back-office session token, from `Authorization: Bearer ...` or the
    `X-Admin-Key` header the app sends."""
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_admin_key


def _online(request: Request) -> bool:
    return request.app.state.runtime.online


def require_admin(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Depends(admin_token)],
) -> AdminUser:
    """The signed-in back-office user making this request."""
    user = user_for_token(db, token)
    if user is None:
        raise HTTPException(401, "Sign in to the back office")
    request.state.admin_user = user
    request.app.state.offline.remember_admin(token)
    return user


def _offline_tenant(request: Request, token: str, kiosk_key: str, api_key: str, tenant_id: str):
    """The client of a kiosk request while Supabase cannot be reached, from
    what was seen online since the server started (`offline.py`)."""
    offline = request.app.state.offline
    if tenant_id:
        if not offline.admin_signed_in(token):
            raise HTTPException(401, "Sign in to the back office")
        tenant = offline.tenant_by_id(tenant_id)
    elif api_key:
        found = offline.tenant_for_api_key(api_key)
        if found is None:
            raise HTTPException(401, "Unknown or revoked API key")
        tenant = found[1]
    else:
        tenant = offline.tenant_for_key(kiosk_key)
    if tenant is None:
        raise HTTPException(503, "This kiosk has not connected to Medora since the server started; connect to the internet once.")
    if not tenant.active:
        raise HTTPException(403, "This client is switched off")
    return tenant


def current_tenant(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Depends(admin_token)],
    x_kiosk_key: Annotated[str, Header()] = "",
    x_api_key: Annotated[str, Header()] = "",
    x_tenant_id: Annotated[str, Header()] = "",
) -> Tenant:
    """The client a request belongs to. In order: the back office previewing
    a client's kiosk (signed in, plus a tenant id), a client's own system
    (`X-Api-Key`), a kiosk (`X-Kiosk-Key`), else the default client.
    Without internet, answered from memory (`offline.py`)."""
    if not _online(request):
        # Memory first, so an offline request does not wait on the database;
        # a kiosk not seen yet is still tried there.
        try:
            return _offline_tenant(request, token, x_kiosk_key, x_api_key, x_tenant_id)
        except HTTPException as e:
            if e.status_code != 503 and e.status_code != 401:
                raise
    try:
        return _tenant(request, db, token, x_kiosk_key, x_api_key, x_tenant_id)
    except UNREACHABLE:
        # The internet dropped before the next check noticed.
        return _offline_tenant(request, token, x_kiosk_key, x_api_key, x_tenant_id)


def _tenant(request, db, token, x_kiosk_key, x_api_key, x_tenant_id) -> Tenant:
    offline = request.app.state.offline
    if x_tenant_id:
        require_admin(request, db, token)
        tenant = db.get(Tenant, x_tenant_id)
        if tenant is None:
            raise HTTPException(404, "Client not found")
        offline.remember_tenant(tenant, None)
        return tenant
    if x_api_key:
        api_key = find_api_key(db, x_api_key)
        if api_key is None:
            raise HTTPException(401, "Unknown or revoked API key")
        # Picked up by the request-log middleware in main.py.
        request.state.api_key = (api_key.id, api_key.tenant_id)
        tenant = db.get(Tenant, api_key.tenant_id)
        if tenant is not None:
            offline.remember_tenant(tenant, None)
            offline.remember_api_key(x_api_key, api_key.id, api_key.tenant_id)
    else:
        tenant = find_tenant(db, x_kiosk_key)
        if tenant is not None:
            offline.remember_tenant(tenant, x_kiosk_key)
    if tenant is None:
        raise HTTPException(401, "Unknown kiosk key")
    if not tenant.active:
        raise HTTPException(403, "This client is switched off")
    return tenant


def note_api_key(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_api_key: Annotated[str, Header()] = "",
) -> None:
    """For routes that do not need to know the client: an API key, when one
    is sent, must still be valid, and its use is still logged (online)."""
    if not x_api_key:
        return
    offline = request.app.state.offline
    if _online(request):
        try:
            api_key = find_api_key(db, x_api_key)
        except UNREACHABLE:
            api_key = None
            if offline.tenant_for_api_key(x_api_key) is not None:
                return
        if api_key is None:
            raise HTTPException(401, "Unknown or revoked API key")
        request.state.api_key = (api_key.id, api_key.tenant_id)
        offline.remember_api_key(x_api_key, api_key.id, api_key.tenant_id)
    elif offline.tenant_for_api_key(x_api_key) is None:
        try:
            api_key = find_api_key(db, x_api_key)
        except UNREACHABLE:
            api_key = None
        if api_key is None:
            raise HTTPException(401, "Unknown or revoked API key")


Db = Annotated[Session, Depends(get_db)]
Kiosk = Annotated[Tenant, Depends(current_tenant)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Admin = Depends(require_admin)
CurrentAdmin = Annotated[AdminUser, Depends(require_admin)]
