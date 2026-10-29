"""Runs files through plan -> approve -> load and keeps the history."""

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from ..knowledge_models import IngestionReject, IngestionRun, KnowledgeBase
from ..llm import Llm, LlmError
from . import load as loader
from . import records
from .articles import ARTICLE_PLAN, extract_article
from .plan import EntityOutput, Plan
from .planner import make_plan
from .sniff import Sniffed, sniff
from .transform import Staged, apply_plan

PREVIEW_RECORDS = 5000
# A load is refused when more than this share of values fails validation:
# the mapping is probably wrong, and a human should look before forcing it.
MAX_REJECT_RATE = 0.4
# Plans the model is less sure of than this are flagged for a closer look.
REVIEW_BELOW_CONFIDENCE = 0.8
# New names from a file with no links, in the preview sample, that count as
# flooding a table with terms nothing refers to.
FLOOD_THRESHOLD = 2000

PLANNING_FAILED = "Planning failed"

KNOWLEDGE_TABLES = ("diseases", "symptoms", "drugs", "disease_links", "precautions")
# Tables of the earlier layout that the current one replaces.
LEGACY_ONLY_TABLES = ("disease_symptoms", "medicines")


class IngestError(Exception):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def legacy_tables(engine: Engine) -> list[str]:
    """Knowledge tables present in an older, incompatible layout."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    found = [t for t in LEGACY_ONLY_TABLES if t in existing]
    for table in ("diseases", "symptoms", "drugs"):
        if table in existing and "normalized_name" not in {
            c["name"] for c in inspector.get_columns(table)
        }:
            found.append(table)
    if found:
        # Links and precautions belong to whichever layout the entities have.
        found += [t for t in ("disease_links", "precautions") if t in existing]
    return sorted(set(found))


def init_db(engine: Engine, replace_legacy: bool = False) -> list[str]:
    """Creates the knowledge tables. Returns the legacy tables it replaced.

    Legacy tables are only ever dropped when asked to, and only when every
    one of them is empty.
    """
    legacy = legacy_tables(engine)
    if legacy and not replace_legacy:
        raise IngestError(
            "This database has knowledge tables in an older layout: "
            + ", ".join(legacy)
            + ". Re-run with --replace-legacy to replace them (only possible while they are empty)."
        )
    with engine.begin() as connection:
        for table in legacy:
            rows = connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar()
            if rows:
                raise IngestError(
                    f"Refusing to replace legacy table {table!r}: it holds {rows} rows."
                )
        for table in legacy:
            cascade = " CASCADE" if connection.dialect.name == "postgresql" else ""
            connection.execute(text(f'DROP TABLE "{table}"{cascade}'))
    KnowledgeBase.metadata.create_all(engine)
    return legacy


class Pipeline:
    def __init__(self, engine: Engine, llm: Llm, cache_dir: Path):
        self.engine = engine
        self.llm = llm
        # Model output is cached by file content, so re-planning the same file
        # (for example against another database) costs no model calls and
        # gives the identical, already-reviewed plan.
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    # --- cache ------------------------------------------------------------

    def _cache_path(self, sha: str) -> Path:
        return self.cache_dir / f"{sha}.json"

    def _cached(self, sha: str) -> dict:
        path = self._cache_path(sha)
        return json.loads(path.read_text()) if path.exists() else {}

    def _store(self, sha: str, data: dict) -> None:
        self._cache_path(sha).write_text(json.dumps(data, ensure_ascii=False, indent=1))

    # --- plan -------------------------------------------------------------

    async def plan_file(
        self, path: Path, filename: str | None = None
    ) -> tuple[IngestionRun, bool]:
        """Plans one file. Returns the run and whether it was created now
        (False when identical content has been seen before). `filename` is
        the name to show when the file is stored under another one."""
        filename = filename or path.name
        sha = file_sha256(path)
        with Session(self.engine, expire_on_commit=False) as db:
            existing = db.scalar(select(IngestionRun).where(IngestionRun.sha256 == sha))
            if existing is not None and existing.note.startswith(PLANNING_FAILED):
                # The model could not be reached last time; try again.
                db.delete(existing)
                db.commit()
            elif existing is not None:
                return existing, False

        sniffed = sniff(path)
        note = ""
        article: dict | None = None
        try:
            plan, article = await self._decide(path, filename, sha, sniffed)
        except LlmError as e:
            plan = Plan(content="none", verdict="junk", confidence=0, reason=str(e))
            status, note = "failed", f"{PLANNING_FAILED}: {e}"
        else:
            if plan.verdict != "usable":
                status, note = "skipped", plan.reason or plan.summary
            else:
                status = "planned"

        stats: dict = {
            "source": str(path),
            "format": sniffed.format,
            "delimiter": sniffed.delimiter,
            "record_path": sniffed.record_path,
        }
        if status == "planned":
            staged = apply_plan(
                *self._plan_and_records(plan, path, stats, article), limit=PREVIEW_RECORDS
            )
            stats["preview"] = staged.summary()
            stats["needs_review"] = self._review_reasons(plan, staged, article)
            if article and article["dropped"]:
                # Already removed by the grounding check; kept for the record.
                stats["dropped_not_in_article"] = article["dropped"]

        run = IngestionRun(
            filename=filename,
            sha256=sha,
            size_bytes=sniffed.size_bytes,
            status=status,
            note=note,
            plan=plan.model_dump(),
            stats=stats,
        )
        with Session(self.engine, expire_on_commit=False) as db:
            db.add(run)
            db.commit()
        return run, True

    async def _decide(
        self, path: Path, filename: str, sha: str, sniffed: Sniffed
    ) -> tuple[Plan, dict | None]:
        if sniffed.format in ("code", "binary", "empty"):
            what = {"code": "Source code", "binary": "A binary file", "empty": "An empty file"}
            return (
                Plan(
                    content="none",
                    verdict="not_data",
                    confidence=1,
                    summary=what[sniffed.format] + ", not a dataset.",
                    model="format check",
                ),
                None,
            )

        cached = self._cached(sha)
        if sniffed.format == "text":
            # Prose has no columns to plan. The extraction step itself decides
            # whether this is an article about one disease.
            if "plan" not in cached:
                try:
                    record, dropped = await extract_article(
                        self.llm, path.read_text(encoding="utf-8", errors="replace")
                    )
                except LlmError as e:
                    if "article" not in str(e):
                        raise
                    cached["plan"] = Plan(
                        content="none", verdict="junk", confidence=0.9,
                        summary="Free text that is not an article about one disease.",
                        reason=str(e), model=self.llm.name,
                    ).model_dump()  # fmt: skip
                else:
                    cached["article"] = {"record": record, "dropped": dropped}
                    cached["plan"] = Plan(
                        content="article", verdict="usable", confidence=0.9,
                        summary=f"Article about {record['disease']}",
                        model=self.llm.name,
                    ).model_dump()  # fmt: skip
                self._store(sha, cached)
            return Plan.model_validate(cached["plan"]), cached.get("article")

        if "plan" in cached:
            plan = Plan.model_validate(cached["plan"])
        else:
            plan = await make_plan(self.llm, filename, sniffed)
            cached["plan"] = plan.model_dump()
            self._store(sha, cached)
        if plan.verdict == "usable" and plan.content == "article":
            raise LlmError(f"The plan treats a {sniffed.format} file as an article")
        return plan, None

    @staticmethod
    def _review_reasons(plan: Plan, staged: Staged, article: dict | None) -> list[str]:
        reasons = []
        if plan.confidence < REVIEW_BELOW_CONFIDENCE:
            reasons.append(f"model confidence is {plan.confidence:.2f}")
        if staged.reject_rate > MAX_REJECT_RATE:
            reasons.append(
                f"{staged.reject_rate:.0%} of sampled values fail validation; the mapping may be wrong"
            )
        if not any(staged.entities.values()):
            reasons.append("the sample produced nothing to load")
        if not staged.links and not staged.precautions:
            for table, drafts in staged.entities.items():
                creating = sum(d.create for d in drafts.values())
                if creating >= FLOOD_THRESHOLD:
                    reasons.append(
                        f"would add thousands of standalone {table} not tied to any disease "
                        f"({creating:,} in the first {staged.records:,} records); "
                        "consider revising to enrich_only"
                    )
        return reasons

    def _plan_and_records(
        self, plan: Plan, path: Path, stats: dict, article: dict | None
    ) -> tuple[Plan, Iterator[dict]]:
        if plan.content == "article":
            if article is None:
                article = self._cached(file_sha256(path)).get("article")
            if article is None:
                raise IngestError("The article extraction is missing; plan the file again")
            return ARTICLE_PLAN, iter([article["record"]])
        fmt = stats["format"]
        if fmt == "csv":
            return plan, records.iter_csv(path, stats["delimiter"])
        if fmt == "json":
            return plan, records.iter_json(path, stats["record_path"])
        if fmt == "obo":
            return plan, records.iter_obo(path)
        if fmt == "owl":
            return plan, records.iter_owl(path)
        if fmt == "xml":
            return plan, records.iter_xml(path, stats["record_path"])
        raise IngestError(f"Cannot read records from a {fmt} file")

    # --- review ------------------------------------------------------------

    async def revise(self, run_id: int, instruction: str) -> IngestionRun:
        """Re-plans a run following a reviewer's instruction in plain words."""
        with Session(self.engine, expire_on_commit=False) as db:
            run = self._get(db, run_id)
            if run.status not in ("planned", "approved", "failed", "skipped"):
                raise IngestError(f"Run {run_id} is {run.status} and cannot be revised")
            path = Path(run.stats["source"])
            previous = Plan.model_validate(run.plan)
            if previous.content == "article" or run.stats["format"] not in ("csv", "json", "obo", "owl", "xml"):
                raise IngestError("Only plans for record files can be revised")
            sniffed = sniff(path)
            plan = await make_plan(self.llm, run.filename, sniffed, revise=(previous, instruction))
            stats = {k: run.stats[k] for k in ("source", "format", "delimiter", "record_path")}
            stats["revised"] = [*run.stats.get("revised", []), instruction]
            if plan.verdict == "usable":
                staged = apply_plan(
                    *self._plan_and_records(plan, path, stats, None), limit=PREVIEW_RECORDS
                )
                stats["preview"] = staged.summary()
                stats["needs_review"] = self._review_reasons(plan, staged, None)
                run.status, run.note = "planned", ""
            else:
                run.status, run.note = "skipped", plan.reason or plan.summary
            run.plan, run.stats = plan.model_dump(), stats
            db.commit()
            self._store(run.sha256, {"plan": plan.model_dump()})
            return run

    def reject(self, run_id: int, reason: str) -> IngestionRun:
        """A reviewer's decision that a file must not be loaded."""
        with Session(self.engine, expire_on_commit=False) as db:
            run = self._get(db, run_id)
            if run.status == "loaded":
                raise IngestError(f"Run {run_id} is loaded; undo it instead")
            run.status, run.note = "skipped", f"Rejected by reviewer: {reason}"
            db.commit()
            return run

    def forget(self, run_id: int) -> None:
        """Drops a run that was never loaded, and its cached plan, so the
        file can be planned from scratch."""
        with Session(self.engine) as db:
            run = self._get(db, run_id)
            if run.status == "loaded":
                raise IngestError(f"Run {run_id} is loaded; undo it first")
            self._cache_path(run.sha256).unlink(missing_ok=True)
            db.delete(run)
            db.commit()

    # --- approve / load / undo --------------------------------------------

    def approve(self, run_id: int) -> IngestionRun:
        with Session(self.engine, expire_on_commit=False) as db:
            run = self._get(db, run_id)
            if run.status not in ("planned", "failed", "undone"):
                raise IngestError(f"Run {run_id} is {run.status}; only planned runs can be approved")
            if Plan.model_validate(run.plan).verdict != "usable":
                raise IngestError(f"Run {run_id} has no usable plan")
            run.status, run.note = "approved", ""
            db.commit()
            return run

    def load(self, run_id: int, force: bool = False) -> IngestionRun:
        """Loads an approved run in a single transaction: all of it or none."""
        with Session(self.engine, expire_on_commit=False) as db:
            run = self._get(db, run_id)
            if run.status != "approved":
                raise IngestError(f"Run {run_id} is {run.status}; approve it before loading")
            path = Path(run.stats["source"])
            if not path.exists():
                raise IngestError(f"Source file is gone: {path}")
            if file_sha256(path) != run.sha256:
                raise IngestError(f"{path.name} changed since it was planned; plan it again")

            plan = Plan.model_validate(run.plan)
            staged = apply_plan(*self._plan_and_records(plan, path, run.stats, None))
            stats = {**run.stats, "staged": staged.summary()}

            problem = None
            if not any(staged.entities.values()):
                problem = "Nothing to load: no record produced a valid row."
            elif staged.reject_rate > MAX_REJECT_RATE and not force:
                problem = (
                    f"{staged.reject_rate:.0%} of values failed validation "
                    f"(limit {MAX_REJECT_RATE:.0%}). The mapping is probably wrong; "
                    "nothing was loaded."
                )
            db.query(IngestionReject).filter(IngestionReject.run_id == run_id).delete()
            if problem:
                db.add_all(
                    IngestionReject(run_id=run_id, reason=r, value=v)
                    for r, v in staged.reject_samples
                )
                run.status, run.note, run.stats = "failed", problem, stats
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
                return run

            try:
                stats["loaded"] = loader.apply(db, staged, run_id)
            except Exception as e:
                db.rollback()
                run = self._get(db, run_id)
                run.status, run.note = "failed", f"Load failed and was rolled back: {e}"[:2000]
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
                return run
            run.status, run.note, run.stats = "loaded", "", stats
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return run

    def undo(self, run_id: int) -> dict:
        with Session(self.engine) as db:
            run = self._get(db, run_id)
            if run.status != "loaded":
                raise IngestError(f"Run {run_id} is {run.status}; only loaded runs can be undone")
            removed = loader.undo(db, run_id)
            run.status, run.stats = "undone", {**run.stats, "undone": removed}
            db.commit()
            return removed

    def runs(self) -> list[IngestionRun]:
        with Session(self.engine, expire_on_commit=False) as db:
            return list(db.scalars(select(IngestionRun).order_by(IngestionRun.id)))

    @staticmethod
    def _get(db: Session, run_id: int) -> IngestionRun:
        run = db.get(IngestionRun, run_id)
        if run is None:
            raise IngestError(f"There is no run {run_id}")
        return run


def load_order(run: IngestionRun) -> int:
    """Curated article text first, so it wins the fill-if-empty rule; plans
    that only enrich existing rows last, when there are rows to enrich."""
    plan = Plan.model_validate(run.plan)
    if plan.content == "article":
        return 0
    enrich_only = plan.outputs and all(
        isinstance(o, EntityOutput) and o.mode == "enrich_only" for o in plan.outputs
    )
    return 2 if enrich_only else 1
