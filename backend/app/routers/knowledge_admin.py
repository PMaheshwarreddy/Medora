"""Back office: browsing the medical knowledge and running ingestion."""

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from sqlalchemy import String, cast, func, inspect, or_, select

from ..deps import Admin, AppSettings, Db
from ..ingest.pipeline import IngestError, Pipeline, init_db, legacy_tables
from ..ingest.transform import normalize
from ..knowledge_models import (
    ENTITY_FIELDS,
    ENTITY_MODELS,
    Disease,
    DiseaseLink,
    Drug,
    IngestionReject,
    IngestionRun,
    Precaution,
    Symptom,
)
from ..llm import LlmError
from ..schemas import ApiModel
from ..tenancy import record

router = APIRouter(prefix="/api/admin/knowledge", dependencies=[Admin])

_CHUNK = 1024 * 1024


def _pipeline(request: Request) -> Pipeline:
    return request.app.state.ingest


def _ready(request: Request) -> bool:
    return "ingestion_runs" in inspect(request.app.state.engine).get_table_names()


def _require_ready(request: Request) -> None:
    if not _ready(request):
        raise HTTPException(409, "The knowledge tables have not been created yet")


def _fail(error: Exception):
    raise HTTPException(409 if isinstance(error, IngestError) else 502, str(error)) from error


# --- browsing ---------------------------------------------------------------


@router.get("/summary")
def summary(request: Request, db: Db) -> dict:
    if not _ready(request):
        return {"ready": False, "legacyTables": legacy_tables(request.app.state.engine)}

    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where))

    return {
        "ready": True,
        "diseases": count(Disease),
        "symptoms": count(Symptom),
        "drugs": count(Drug),
        "symptomLinks": count(DiseaseLink, DiseaseLink.symptom_id.is_not(None)),
        "drugLinks": count(DiseaseLink, DiseaseLink.drug_id.is_not(None)),
        "precautions": count(Precaution),
        "diseasesWithDescription": count(Disease, Disease.description != ""),
    }


@router.post("/init")
def create_tables(request: Request) -> dict:
    """Creates the knowledge tables. Never replaces tables of an older
    layout; that needs the command line, on purpose."""
    try:
        init_db(request.app.state.engine)
    except IngestError as e:
        _fail(e)
    record(request.app.state.engine, "knowledge.init", "Knowledge tables created")
    return {"ready": True}


@router.get("/{table}")
def browse(
    table: str,
    request: Request,
    db: Db,
    q: str = "",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    if table not in ENTITY_MODELS:
        raise HTTPException(404, "Unknown table")
    _require_ready(request)
    model = ENTITY_MODELS[table]
    query = select(model)
    if key := normalize(q):
        # Aliases are searched as stored text; names by their matching key.
        query = query.where(
            or_(
                model.normalized_name.contains(key),
                func.lower(cast(model.aliases, String)).contains(q.strip().lower()),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(model.name).limit(limit).offset(offset)).all()
    link_column = {
        "diseases": DiseaseLink.disease_id,
        "symptoms": DiseaseLink.symptom_id,
        "drugs": DiseaseLink.drug_id,
    }[table]
    links = dict(
        db.execute(
            select(link_column, func.count())
            .where(link_column.in_([r.id for r in rows]))
            .group_by(link_column)
        ).all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "aliases": r.aliases or [],
                "links": links.get(r.id, 0),
                **{f: getattr(r, f) for f in ENTITY_FIELDS[table]},
            }
            for r in rows
        ],
    }


@router.get("/diseases/{disease_id}")
def disease_detail(disease_id: int, request: Request, db: Db) -> dict:
    _require_ready(request)
    disease = db.get(Disease, disease_id)
    if disease is None:
        raise HTTPException(404, "Disease not found")
    symptoms = db.scalars(
        select(Symptom.name)
        .join(DiseaseLink, DiseaseLink.symptom_id == Symptom.id)
        .where(DiseaseLink.disease_id == disease_id)
        .order_by(Symptom.name)
    ).all()
    drugs = db.scalars(
        select(Drug.name)
        .join(DiseaseLink, DiseaseLink.drug_id == Drug.id)
        .where(DiseaseLink.disease_id == disease_id)
        .order_by(Drug.name)
    ).all()
    precautions = db.scalars(
        select(Precaution.precaution).where(Precaution.disease_id == disease_id)
    ).all()
    return {
        "id": disease.id,
        "name": disease.name,
        "aliases": disease.aliases or [],
        "description": disease.description,
        "causes": disease.causes,
        "symptoms": symptoms,
        "drugs": drugs,
        "precautions": precautions,
    }


# --- ingestion --------------------------------------------------------------


def _run_out(run: IngestionRun, rejects: list | None = None) -> dict:
    plan = run.plan
    out = {
        "id": run.id,
        "filename": run.filename,
        "sizeBytes": run.size_bytes,
        "status": run.status,
        "note": run.note,
        "createdAt": run.created_at.isoformat(),
        "summary": plan.get("summary", ""),
        "verdict": plan.get("verdict", ""),
        "confidence": plan.get("confidence", 0),
        "content": plan.get("content", ""),
        "needsReview": run.stats.get("needs_review", []),
        "preview": run.stats.get("preview"),
        "loaded": run.stats.get("loaded"),
    }
    if rejects is not None:
        out |= {
            "reason": plan.get("reason", ""),
            "model": plan.get("model", ""),
            "outputs": plan.get("outputs", []),
            "revised": run.stats.get("revised", []),
            "droppedNotInArticle": run.stats.get("dropped_not_in_article", []),
            "rejects": [{"reason": r, "value": v} for r, v in rejects],
        }
    return out


@router.get("/ingest/runs")
def list_runs(request: Request) -> list[dict]:
    _require_ready(request)
    return [_run_out(r) for r in reversed(_pipeline(request).runs())]


@router.get("/ingest/runs/{run_id}")
def run_detail(run_id: int, request: Request, db: Db) -> dict:
    _require_ready(request)
    run = db.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    rejects = db.execute(
        select(IngestionReject.reason, IngestionReject.value)
        .where(IngestionReject.run_id == run_id)
        .limit(60)
    ).all()
    return _run_out(run, rejects)


@router.post("/ingest/upload", status_code=201)
async def upload(file: UploadFile, request: Request, settings: AppSettings) -> dict:
    """Stores a source file and has the AI plan it. Nothing is loaded until
    the plan is approved."""
    _require_ready(request)
    # The uploaded name is only displayed; on disk the file gets a generated
    # name, so path tricks in it cannot escape the knowledge folder.
    original = Path(file.filename or "").name
    if not original:
        raise HTTPException(400, "The file has no name")
    folder = Path(settings.data_dir) / "knowledge"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (uuid.uuid4().hex + Path(original).suffix.lower()[:16])
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "The file is empty")
        run, created = await _pipeline(request).plan_file(target, filename=original[:255])
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if not created:
        target.unlink(missing_ok=True)
        raise HTTPException(
            409, f"This file's content was already ingested as {run.filename!r} (run {run.id})"
        )
    record(request.app.state.engine, "knowledge.planned", f"{original}: {run.status}")
    return _run_out(run)


class ReasonBody(ApiModel):
    text: str


@router.post("/ingest/runs/{run_id}/{action}")
async def act(
    run_id: int, action: str, request: Request, body: ReasonBody | None = None
) -> dict:
    """approve | reject | revise | load | undo."""
    _require_ready(request)
    pipeline = _pipeline(request)
    text = (body.text if body else "").strip()
    try:
        if action == "approve":
            run = pipeline.approve(run_id)
        elif action == "reject":
            if not text:
                raise HTTPException(422, "Say why the file is rejected")
            run = pipeline.reject(run_id, text)
        elif action == "revise":
            if not text:
                raise HTTPException(422, "Say what should change")
            run = await pipeline.revise(run_id, text)
        elif action == "load":
            # Large files take a while; keep the event loop free meanwhile.
            from anyio import to_thread

            run = await to_thread.run_sync(pipeline.load, run_id)
        elif action == "undo":
            pipeline.undo(run_id)
            run = next(r for r in pipeline.runs() if r.id == run_id)
        else:
            raise HTTPException(404, "Unknown action")
    except (IngestError, LlmError) as e:
        _fail(e)
    level = "error" if run.status == "failed" else "info"
    record(
        request.app.state.engine,
        f"knowledge.{action}",
        f"{run.filename}: {run.status}" + (f" ({run.note})" if run.note else ""),
        level=level,
    )
    return _run_out(run)
