"""Knowledge base pipeline: python -m app.kb <command>

  init                 create the tables (safe to repeat)
  load <key>... | all  read, check and load sources (see app/kb/sources.py)
  link                 connect rows across sources (conditions, drugs)
  embed [n]            compute MedCPT vectors for passages that lack one (trusted first; resumable)
  snapshot             save the allowed passages and vectors for offline search (data/rag_cache)
  rebuild              everything, in order, into an empty or existing database:
                       init, load all, link, embed, snapshot
  quantize             int8 copy of the MedCPT Cross-Encoder (run as: uv run --with onnx python -m app.kb quantize)
  search <question>    try the guideline search (pass 1 style) and print the passages
  status               what is loaded, quarantined and rejected
"""

import importlib
import logging
import sys
import time
from pathlib import Path

from ..settings import Settings
from . import load as loader
from .sources import BY_KEY, REJECTED, SOURCES
from .text import file_sha256

ROOT = Path(__file__).resolve().parents[3]


def _order(keys: list[str]) -> list[str]:
    done: list[str] = []

    def visit(k: str) -> None:
        if k in done:
            return
        for dep in BY_KEY[k].after:
            if dep in keys:
                visit(dep)
        done.append(k)

    for k in keys:
        visit(k)
    return done


HF_DIR = ROOT / "backend/data/hf"


def _path(spec: str) -> Path:
    """A local file, or 'hf:<owner>/<name>/<file>' downloaded once into data/hf/."""
    if not spec.startswith("hf:"):
        return ROOT / spec
    owner, name, file = spec[3:].split("/", 2)
    local = HF_DIR / owner / name / file
    if not local.exists():
        import httpx

        local.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{owner}/{name}/resolve/main/{file}"
        print(f"  downloading {url}", flush=True)
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with open(local.with_suffix(local.suffix + ".part"), "wb") as f:
                for block in r.iter_bytes(1 << 20):
                    f.write(block)
        local.with_suffix(local.suffix + ".part").rename(local)
    return local


def cmd_load(conn, keys: list[str], settings: Settings) -> None:
    keys = [s.key for s in SOURCES] if keys == ["all"] else keys
    for k in keys:
        if k not in BY_KEY:
            raise SystemExit(f"Unknown source {k!r}. Known: {', '.join(BY_KEY)}")
    for key in _order(keys):
        source = BY_KEY[key]
        try:
            paths = [_path(f) for f in source.files]
        except Exception as e:  # noqa: BLE001
            print(f"✗ {key}: download failed: {e}")
            continue
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            print(f"✗ {key}: missing {missing}")
            continue
        files = [{"name": p.name, "sha256": file_sha256(p), "bytes": p.stat().st_size} for p in paths]
        reader = importlib.import_module(f"app.kb.readers.{source.reader}")
        started = time.time()
        print(f"… {key}: reading {len(paths)} file(s)", flush=True)
        try:
            bundle = reader.read(source, paths, conn=conn, settings=settings)
            stats = loader.load(conn, source, bundle, files)
        except Exception as e:  # noqa: BLE001 - recorded on the source, then the next one
            logging.exception("load failed")
            loader.mark_failed(conn, source, f"{type(e).__name__}: {e}")
            print(f"✗ {key}: {type(e).__name__}: {e}")
            continue
        print(f"✓ {key} in {time.time() - started:.0f}s: {stats}", flush=True)


def cmd_status(conn) -> None:
    rows = conn.execute(
        """select s.key, s.status, s.production_allowed, s.stats, s.loaded_at,
                  (select count(*) from kb_quarantine q where q.source_id=s.id)
           from kb_sources s order by s.tier, s.key"""
    ).fetchall()
    for key, status, allowed, stats, at, quarantined in rows:
        flag = "reports" if allowed else "testing only"
        print(f"{key:18} {status:8} {flag:12} quarantined={quarantined:<5} {stats}")
    for f, why in REJECTED.items():
        print(f"rejected  {f}: {why}")
    size = conn.execute("select pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
    print("database size:", size)


def _retriever(settings: Settings):
    from .retrieve import Retriever

    return Retriever(settings.knowledge_database_url, testing_sources=settings.knowledge_testing_sources,
                     community_sources=settings.knowledge_community_sources,
                     snapshot_dir=Path(settings.data_dir) / "rag_cache")


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "quantize":  # no database needed
        from .embed import quantize_cross_encoder

        print("written", quantize_cross_encoder())
        return
    conn = loader.connect(settings.knowledge_database_url)
    if cmd == "init":
        loader.init_schema(conn)
        print("tables ready")
    elif cmd == "load":
        loader.init_schema(conn)
        cmd_load(conn, rest or ["all"], settings)
    elif cmd == "link":
        print(loader.link(conn))
    elif cmd == "embed":
        from .embed import embed_missing

        embed_missing(conn, limit=int(rest[0]) if rest else None, url=settings.knowledge_database_url)
    elif cmd == "snapshot":
        print(_retriever(settings).save_snapshot(), "passages saved for offline search")
    elif cmd == "rebuild":
        loader.init_schema(conn)
        cmd_load(conn, ["all"], settings)
        print(loader.link(conn))
        from .embed import embed_missing

        embed_missing(conn, url=settings.knowledge_database_url)
        print(_retriever(settings).save_snapshot(), "passages saved for offline search")
        cmd_status(conn)
    elif cmd == "search":
        from .retrieve import DIAGNOSIS, TREATMENT

        question = " ".join(rest)
        for kind in (DIAGNOSIS, TREATMENT):
            started = time.time()
            ev = _retriever(settings).search(question, kind)
            print(f"\n== {kind} ({time.time() - started:.1f}s) {ev.note}")
            for p in ev.passages:
                print(f"  {p.score:6.2f}  tier {p.tier}  {p.breadcrumb}" + (f" (p.{p.page})" if p.page else ""))
    elif cmd == "status":
        cmd_status(conn)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
