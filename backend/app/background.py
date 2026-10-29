"""Background work: watching for internet, and copying what waited.

Every 10 s the server checks whether the internet is there
(`runtime.online`). When it is back, visits and reports made offline
(held in memory by `offline.py`) are copied into the database, which is
Supabase. The older mirror to a second database (`cloud_database_url`) is
idle while that setting is empty. Nothing a patient does depends on this.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import Engine, create_engine, func, or_, select, update
from sqlalchemy.orm import Session

from .models import ActivityLog, IntakeSession, Tenant, TriageReport
from .tenancy import ensure_schema

log = logging.getLogger("medora.background")

# Hosts whose reachability stands for "the internet is there".
_PROBE = ("generativelanguage.googleapis.com", 443)
CHECK_EVERY = 10
SYNC_EVERY = 20
BATCH = 300

# Parents before children. Tenants change after creation, the rest do not.
_MIRRORED = (Tenant, IntakeSession, TriageReport, ActivityLog)


@dataclass
class SyncState:
    configured: bool = False
    last_success: datetime | None = None
    last_error: str = ""
    mirrored_total: int = 0


@dataclass
class Runtime:
    online: bool = True
    sync: SyncState = field(default_factory=SyncState)


async def is_online(timeout: float = 3.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(*_PROBE), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    return True


def _unsynced(model):
    if model is Tenant:
        return or_(Tenant.synced_at.is_(None), Tenant.updated_at > Tenant.synced_at)
    return model.synced_at.is_(None)


def pending(local: Engine) -> int:
    with Session(local) as db:
        return sum(
            db.scalar(select(func.count()).select_from(m).where(_unsynced(m))) for m in _MIRRORED
        )


def mirror_once(local: Engine, cloud: Engine) -> int:
    """Copies one batch of unmirrored rows per table. Returns how many."""
    copied = 0
    with Session(local) as source, Session(cloud) as target:
        for model in _MIRRORED:
            rows = source.scalars(select(model).where(_unsynced(model)).limit(BATCH)).all()
            if not rows:
                continue
            columns = [c.key for c in model.__table__.columns if c.key != "synced_at"]
            for row in rows:
                # merge = insert, or update when the key is already there, so
                # a batch that is retried after a failure does no harm.
                target.merge(model(**{c: getattr(row, c) for c in columns}))
            target.commit()
            values = {"synced_at": datetime.now(timezone.utc)}
            if model is Tenant:
                # Marking a client as mirrored must not count as a new change.
                values["updated_at"] = Tenant.updated_at
            key = model.__table__.primary_key.columns[0]
            source.execute(
                update(model).where(key.in_([getattr(r, key.key) for r in rows])).values(values)
            )
            source.commit()
            copied += len(rows)
    return copied


async def run(runtime: Runtime, local: Engine, cloud_url: str, offline=None, force_offline: bool = False) -> None:
    """Loops until cancelled. `offline` (an `offline.OfflineState`) has its
    waiting visits copied into the database whenever the internet is back."""
    cloud: Engine | None = None
    runtime.sync.configured = bool(cloud_url)
    since_sync = SYNC_EVERY
    while True:
        runtime.online = not force_offline and await is_online()
        since_sync += CHECK_EVERY
        if offline is not None and runtime.online and offline.pending():
            try:
                await asyncio.to_thread(offline.flush, local)
            except Exception as e:
                log.warning("Could not copy offline visits yet: %s", str(e).splitlines()[0][:200])
        if cloud_url and runtime.online and since_sync >= SYNC_EVERY:
            since_sync = 0
            try:
                if cloud is None:
                    cloud = create_engine(
                        cloud_url, pool_pre_ping=True, connect_args={"connect_timeout": 8}
                    )
                    await asyncio.to_thread(ensure_schema, cloud)
                while copied := await asyncio.to_thread(mirror_once, local, cloud):
                    runtime.sync.mirrored_total += copied
                runtime.sync.last_success = datetime.now(timezone.utc)
                runtime.sync.last_error = ""
            except Exception as e:
                runtime.sync.last_error = str(e).splitlines()[0][:300]
                log.warning("Cloud mirror failed: %s", runtime.sync.last_error)
        await asyncio.sleep(CHECK_EVERY)
