"""Working without internet, with no local database.

Supabase is the only database (the user's decision of 2026-10-17, kept on
2026-10-18 when offline reports were added). Without internet it cannot be
reached, so this module keeps, in memory only:

- what is needed to serve a kiosk: each client's switches by kiosk key, the
  API keys, and the back-office sign-ins seen while online (so a preview
  opened from the back office keeps working);
- each visit and its report, so the patient gets the report and its PDF;
- activity-log lines that could not be written.

When the internet returns, `flush` copies the visits, reports and log lines
into Supabase. Nothing is written to disk: if the server stops while
offline, what was not yet copied is lost, and a server started without
internet has nothing to serve from (start it online).
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from .models import ActivityLog, IntakeSession, Tenant, TriageReport
from .patients import service as patients
from .tenancy import hash_key, record as write_record

log = logging.getLogger("medora.offline")

# A copied visit stays in memory this long, for the report and PDF.
KEEP_STORED = 2 * 3600
# At most this many visits wait for the internet; the oldest copied ones go first.
MAX_VISITS = 1000

# How long a back-office sign-in seen online is trusted once offline.
ADMIN_GRACE = timedelta(hours=12)

# Errors that mean "the database cannot be reached", not a bug.
UNREACHABLE = (DBAPIError, OSError, TimeoutError)


def _snapshot(row) -> SimpleNamespace:
    """A detached copy of a row's columns, safe to keep after its session."""
    return SimpleNamespace(**{c.key: getattr(row, c.key) for c in row.__table__.columns})


@dataclass
class Visit:
    session: IntakeSession
    report: dict | None = None
    session_stored: bool = False
    report_stored: bool = False
    at: float = field(default_factory=time.monotonic)

    @property
    def pending(self) -> bool:
        return not self.session_stored or (self.report is not None and not self.report_stored)


class OfflineState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tenants_by_key: dict[str, SimpleNamespace] = {}  # kiosk key hash ("" = default)
        self._tenants_by_id: dict[str, SimpleNamespace] = {}
        self._api_keys: dict[str, tuple[str, str]] = {}  # key hash -> (api key id, tenant id)
        self._admins: dict[str, datetime] = {}  # token hash -> session expiry
        self._visits: dict[str, Visit] = {}
        self._log: list[dict] = []
        # Phone hand-offs opened while the database could not be reached
        # (code -> handoff). They live 30 minutes and are never copied: the
        # phone reaches the kiosk server over the hospital's own network.
        self.handoffs: dict[str, SimpleNamespace] = {}

    # --- remembered while online --------------------------------------------

    def remember_tenant(self, tenant: Tenant, kiosk_key: str | None) -> None:
        snap = _snapshot(tenant)
        with self._lock:
            self._tenants_by_id[snap.id] = snap
            if kiosk_key is not None:
                self._tenants_by_key[hash_key(kiosk_key) if kiosk_key else ""] = snap

    def remember_api_key(self, key: str, api_key_id: str, tenant_id: str) -> None:
        with self._lock:
            self._api_keys[hash_key(key)] = (api_key_id, tenant_id)

    def remember_admin(self, token: str) -> None:
        """A sign-in checked against the database just now. Offline it is
        trusted for `ADMIN_GRACE` more, never past the server's life."""
        if token:
            with self._lock:
                self._admins[hash_key(token)] = datetime.now(timezone.utc) + ADMIN_GRACE

    # --- served while offline -----------------------------------------------

    def tenant_for_key(self, kiosk_key: str) -> SimpleNamespace | None:
        return self._tenants_by_key.get(hash_key(kiosk_key) if kiosk_key else "")

    def tenant_by_id(self, tenant_id: str) -> SimpleNamespace | None:
        return self._tenants_by_id.get(tenant_id)

    def tenant_for_api_key(self, key: str) -> tuple[str, SimpleNamespace | None] | None:
        found = self._api_keys.get(hash_key(key))
        if found is None:
            return None
        return found[0], self._tenants_by_id.get(found[1])

    def admin_signed_in(self, token: str) -> bool:
        expires = self._admins.get(hash_key(token)) if token else None
        return expires is not None and expires > datetime.now(timezone.utc)

    # --- visits ---------------------------------------------------------------

    def add_visit(self, session: IntakeSession, stored: bool) -> None:
        with self._lock:
            self._visits[session.id] = Visit(session, session_stored=stored)
            self._trim()

    def visit(self, session_id: str) -> Visit | None:
        with self._lock:
            self._trim()
            return self._visits.get(session_id)

    def set_report(self, session_id: str, report: dict, stored: bool) -> None:
        with self._lock:
            found = self._visits.get(session_id)
            if found is not None:
                found.report, found.report_stored = report, stored

    def pending(self) -> int:
        with self._lock:
            return sum(v.pending for v in self._visits.values()) + len(self._log)

    def _trim(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._visits.items() if not v.pending and now - v.at > KEEP_STORED]:
            del self._visits[key]
        while len(self._visits) > MAX_VISITS:
            stored = [k for k, v in self._visits.items() if not v.pending]
            del self._visits[stored[0] if stored else next(iter(self._visits))]

    # --- the activity log -------------------------------------------------------

    def record(self, engine: Engine, online: bool, event: str, message: str = "",
               tenant_id: str | None = None, level: str = "info") -> None:
        """`tenancy.record` when online; queued for `flush` when not."""
        if online:
            write_record(engine, event, message, tenant_id, level)
            return
        with self._lock:
            self._log.append({
                "event": event, "message": message[:2000], "tenant_id": tenant_id,
                "level": level, "at": datetime.now(timezone.utc),
            })  # fmt: skip
            del self._log[:-2000]

    # --- back online --------------------------------------------------------------

    def flush(self, engine: Engine) -> int:
        """Copies what waited into Supabase. Returns how many rows."""
        with self._lock:
            waiting = [(v, not v.session_stored, None if v.report_stored else v.report)
                       for v in self._visits.values() if v.pending]  # fmt: skip
            lines = list(self._log)
        with Session(engine) as db:
            for visit, session, report in waiting:
                if session:
                    row = db.merge(IntakeSession(**{c.key: getattr(visit.session, c.key)
                                                    for c in IntakeSession.__table__.columns}))  # fmt: skip
                    if not row.patient_id:
                        # The kiosk could not look the patient up offline:
                        # join the record with this phone and name, or a new one.
                        patients.attach(db, row, patients.same_person(db, row))
                        visit.session.patient_id = row.patient_id
                if report is not None:
                    db.merge(TriageReport(session_id=visit.session.id, data=report))
            for line in lines:
                db.add(ActivityLog(**line))
            db.commit()
        copied = len(lines)
        with self._lock:
            for visit, session, report in waiting:
                if session:
                    visit.session_stored = True
                    copied += 1
                # A report made while this ran waits for the next round.
                if report is not None and visit.report is report:
                    visit.report_stored = True
                    copied += 1
            del self._log[: len(lines)]
        if copied:
            log.info("Copied %d offline rows to the database", copied)
        return copied
