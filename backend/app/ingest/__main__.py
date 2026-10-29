"""Command line for the ingestion pipeline.

    python -m app.ingest init-db [--replace-legacy]
    python -m app.ingest plan <folder-or-file>
    python -m app.ingest status
    python -m app.ingest show <run-id>
    python -m app.ingest revise <run-id> "<what to change, in plain words>"
    python -m app.ingest reject <run-id> "<why>"
    python -m app.ingest forget <run-id>
    python -m app.ingest approve <run-id>... | --all
    python -m app.ingest load [<run-id>...] [--force]
    python -m app.ingest undo <run-id>

The database is the one in MEDORA_DATABASE_URL.
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import make_engine
from ..knowledge_models import ENTITY_MODELS, DiseaseLink, IngestionReject, Precaution
from ..settings import Settings
from .pipeline import IngestError, Pipeline, init_db, load_order
from .plan import Plan
from .planner import make_ingest_llm


def _host(url: str) -> str:
    return url.split("@")[-1].split("?")[0] if "@" in url else url


def _table(rows: list[list[str]], header: list[str]) -> None:
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    for row in [header, ["-" * w for w in widths], *rows]:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip())


def _status(pipeline: Pipeline) -> None:
    rows = []
    for run in pipeline.runs():
        plan = Plan.model_validate(run.plan)
        result = run.stats.get("loaded") or run.stats.get("preview") or {}
        if "loaded" in run.stats:
            loaded = run.stats["loaded"]
            detail = ", ".join(
                f"{loaded[t]['created']} {t}" for t in ENTITY_MODELS if loaded.get(t, {}).get("created")
            )
            detail += f", {loaded['links']['created']} links, {loaded['precautions']['created']} precautions"
            detail = "added " + detail.strip(", ")
        elif result:
            detail = f"sample: {result['diseases']} dis, {result['symptoms']} sym, {result['drugs']} drugs, {result['links']} links"
        else:
            detail = ""
        review = "!" if run.stats.get("needs_review") else ""
        rows.append(
            [run.id, run.filename[:38], run.status + review, f"{plan.confidence:.2f}",
             (plan.summary or run.note)[:60], detail]
        )  # fmt: skip
    _table(rows, ["id", "file", "status", "conf", "what it is", "result"])
    with Session(pipeline.engine) as db:
        counts = {t: db.scalar(select(func.count()).select_from(m)) for t, m in ENTITY_MODELS.items()}
        counts["disease_links"] = db.scalar(select(func.count()).select_from(DiseaseLink))
        counts["precautions"] = db.scalar(select(func.count()).select_from(Precaution))
    print("\nIn the database now:", ", ".join(f"{n:,} {t}" for t, n in counts.items()))
    print("('!' after a status means the run is flagged for review: see `show <id>`)")


def _show(pipeline: Pipeline, run_id: int) -> None:
    run = next((r for r in pipeline.runs() if r.id == run_id), None)
    if run is None:
        raise IngestError(f"There is no run {run_id}")
    print(f"Run {run.id}: {run.filename}  [{run.status}]  {run.size_bytes:,} bytes")
    if run.note:
        print("Note:", run.note)
    for reason in run.stats.get("needs_review", []):
        print("Review:", reason)
    print("\nPlan:")
    print(json.dumps(run.plan, indent=2, ensure_ascii=False))
    for key in ("preview", "staged", "loaded", "undone"):
        if key in run.stats:
            print(f"\n{key}:", json.dumps(run.stats[key], indent=2))
    with Session(pipeline.engine) as db:
        rejects = db.execute(
            select(IngestionReject.reason, IngestionReject.value)
            .where(IngestionReject.run_id == run_id)
            .limit(40)
        ).all()
    if rejects:
        print("\nSample of refused values:")
        for reason, value in rejects:
            print(f"  {reason}: {value[:110]}")


async def _plan(pipeline: Pipeline, target: Path) -> None:
    files = sorted(p for p in target.rglob("*") if p.is_file()) if target.is_dir() else [target]
    for i, path in enumerate(files, 1):
        run, created = await pipeline.plan_file(path)
        if created:
            plan = Plan.model_validate(run.plan)
            print(f"[{i}/{len(files)}] {path.name}: {run.status} - {plan.summary or run.note}", flush=True)
        elif run.stats.get("source") != str(path):
            print(f"[{i}/{len(files)}] {path.name}: identical to {run.filename} (run {run.id}), not planned again", flush=True)
        else:
            print(f"[{i}/{len(files)}] {path.name}: already planned (run {run.id}, {run.status})", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init-db")
    p.add_argument("--replace-legacy", action="store_true")
    sub.add_parser("plan").add_argument("target", type=Path)
    sub.add_parser("status")
    sub.add_parser("show").add_argument("run_id", type=int)
    p = sub.add_parser("approve")
    p.add_argument("run_ids", type=int, nargs="*")
    p.add_argument("--all", action="store_true", help="every planned run that is not flagged for review")
    p = sub.add_parser("load")
    p.add_argument("run_ids", type=int, nargs="*")
    p.add_argument("--force", action="store_true", help="load even above the reject-rate limit")
    sub.add_parser("undo").add_argument("run_id", type=int)
    p = sub.add_parser("revise")
    p.add_argument("run_id", type=int)
    p.add_argument("instruction")
    p = sub.add_parser("reject")
    p.add_argument("run_id", type=int)
    p.add_argument("reason")
    sub.add_parser("forget").add_argument("run_id", type=int)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    settings = Settings()
    engine = make_engine(settings.database_url)
    print(f"Database: {_host(settings.database_url)}", file=sys.stderr)
    try:
        if args.command == "init-db":
            replaced = init_db(engine, args.replace_legacy)
            print("Knowledge tables are ready." + (f" Replaced empty legacy tables: {', '.join(replaced)}." if replaced else ""))
            return 0

        pipeline = Pipeline(engine, make_ingest_llm(settings), Path(settings.data_dir) / "ingest_cache")
        if args.command == "plan":
            asyncio.run(_plan(pipeline, args.target))
        elif args.command == "status":
            _status(pipeline)
        elif args.command == "show":
            _show(pipeline, args.run_id)
        elif args.command == "approve":
            ids = args.run_ids or [
                r.id for r in pipeline.runs()
                if args.all and r.status == "planned" and not r.stats.get("needs_review")
            ]  # fmt: skip
            for run_id in ids:
                pipeline.approve(run_id)
            print(f"Approved {len(ids)} run(s).")
        elif args.command == "load":
            runs = [r for r in pipeline.runs() if r.status == "approved" and (not args.run_ids or r.id in args.run_ids)]
            for run in sorted(runs, key=lambda r: (load_order(r), r.id)):
                done = pipeline.load(run.id, force=args.force)
                print(f"run {done.id} {done.filename}: {done.status}" + (f" - {done.note}" if done.note else ""), flush=True)
            if not runs:
                print("No approved runs to load.")
        elif args.command == "revise":
            run = asyncio.run(pipeline.revise(args.run_id, args.instruction))
            print(f"Run {run.id} revised: {run.status}")
            _show(pipeline, run.id)
        elif args.command == "reject":
            pipeline.reject(args.run_id, args.reason)
            print(f"Run {args.run_id} rejected.")
        elif args.command == "forget":
            pipeline.forget(args.run_id)
            print(f"Run {args.run_id} forgotten.")
        elif args.command == "undo":
            print("Removed:", pipeline.undo(args.run_id))
    except IngestError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
