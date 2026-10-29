"""MedCPT encoders on ONNX Runtime (CPU), and the stage that fills
`kb_chunks.embedding`.

MedCPT (NCBI) is three BERT models trained together on PubMed search logs:
- Article Encoder: a passage as (title, text), up to 512 tokens -> 768 numbers.
  Here the title is the passage's breadcrumb.
- Query Encoder: a short query, up to 64 tokens -> 768 numbers.
- Cross-Encoder: scores one (query, passage) pair; used to re-rank.
Vectors are compared by dot product (how MedCPT was trained), so the index
uses inner product. Models: data/models/medcpt/<name>/model.onnx, converted
from the official ncbi/MedCPT-* weights and checked against PyTorch.
"""

import logging
import os
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

log = logging.getLogger("medora.kb.embed")

MODELS = Path(__file__).resolve().parents[2] / "data/models/medcpt"
BATCH = 16


class _Encoder:
    def __init__(self, name: str, max_length: int, prefer_int8: bool = False):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        folder = MODELS / name
        if not (folder / "model.onnx").exists():
            raise FileNotFoundError(f"MedCPT model missing: {folder}/model.onnx")
        model = folder / ("model.int8.onnx" if prefer_int8 and (folder / "model.int8.onnx").exists() else "model.onnx")
        self.model = model.name
        self.tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tok.enable_truncation(max_length=max_length)
        self.tok.enable_padding(pad_id=0, pad_token="[PAD]")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
        self.session = ort.InferenceSession(str(model), opts, providers=["CPUExecutionProvider"])

    def run(self, inputs: list) -> np.ndarray:
        enc = self.tok.encode_batch(inputs)
        feed = {
            "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
            "token_type_ids": np.array([e.type_ids for e in enc], dtype=np.int64),
        }
        return self.session.run(None, feed)[0]


@lru_cache(maxsize=1)
def article_encoder() -> _Encoder:
    return _Encoder("article-encoder", 512)


@lru_cache(maxsize=1)
def query_encoder() -> _Encoder:
    return _Encoder("query-encoder", 64)


@lru_cache(maxsize=1)
def cross_encoder() -> _Encoder:
    # 256 tokens: re-ranking needs the order, and the start of a passage
    # (breadcrumb and first lines) carries it; twice as fast as 512.
    # int8 when present (`python -m app.kb quantize`): on the 24 evaluation
    # questions it chose the same best passage every time (top-3 overlap
    # 86%) and was 28% faster. The two encoders stay fp32: their vectors must
    # match the stored ones.
    return _Encoder("cross-encoder", 256, prefer_int8=True)


def quantize_cross_encoder() -> Path:
    """Writes model.int8.onnx next to the Cross-Encoder. Needs the `onnx`
    package, which the app does not: run with `uv run --with onnx`."""
    from onnxruntime.quantization import QuantType, quantize_dynamic

    folder = MODELS / "cross-encoder"
    out = folder / "model.int8.onnx"
    quantize_dynamic(str(folder / "model.onnx"), str(out), weight_type=QuantType.QInt8)
    return out


def embed_passages(pairs: list[tuple[str, str]]) -> np.ndarray:
    """[(breadcrumb, text)] -> (n, 768)."""
    return article_encoder().run(pairs)


def embed_queries(queries: list[str]) -> np.ndarray:
    return query_encoder().run(queries)


def rerank(query: str, passages: list[str]) -> np.ndarray:
    """Relevance score for each passage (higher is better)."""
    return cross_encoder().run([(query, p) for p in passages]).reshape(-1)


def _vector(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.5f}" for x in v.tolist()) + "]"


def embed_missing(conn, limit: int | None = None, url: str = "") -> None:
    """Embeds every passage that has no vector yet, in batches, then makes
    sure the vector index exists. Resumable: a re-run picks up what is left.
    With `url`, a batch whose write fails (dropped connection, time limit)
    reconnects and is written again, up to 5 times in a row."""
    from .load import connect

    # Trusted sources first (tier 1 -> 5), so a run cut short leaves the most
    # useful passages searchable.
    rows = conn.execute(
        "select k.id, k.breadcrumb, k.body, k.tokens from kb_chunks k join kb_sources s on s.id = k.source_id "
        "where k.embedding is null order by s.tier, k.tokens desc"
        + (f" limit {int(limit)}" if limit else "")
    ).fetchall()
    conn.commit()
    total = len(rows)
    print(f"{total} passages to embed", flush=True)
    started = time.time()
    done = 0
    for i in range(0, total, BATCH * 8):
        block = rows[i : i + BATCH * 8]
        vectors = []
        for j in range(0, len(block), BATCH):
            part = block[j : j + BATCH]
            vectors.extend(embed_passages([(r[1], r[2]) for r in part]))
        params = [(_vector(v), r[0]) for v, r in zip(vectors, block)]
        for attempt in range(6):
            try:
                with conn.cursor() as cur:
                    cur.execute("set statement_timeout = '120s'")
                    cur.executemany("update kb_chunks set embedding = %s::halfvec where id = %s", params)
                conn.commit()
                break
            except Exception as e:  # noqa: BLE001 - network or server trouble: reconnect and retry
                if not url or attempt == 5:
                    raise
                log.warning("Writing vectors failed (%s); reconnecting", str(e)[:120])
                print(f"  write failed ({str(e)[:80]}); reconnecting", flush=True)
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(5 * (attempt + 1))
                conn = connect(url)
        done += len(block)
        rate = done / max(1e-6, time.time() - started)
        print(f"  {done}/{total}  ({rate:.1f}/s, about {(total - done) / max(rate, 1e-6) / 60:.0f} min left)", flush=True)
    conn.execute("set statement_timeout = 0")
    conn.execute(
        "create index if not exists kb_chunks_vec on kb_chunks using hnsw (embedding halfvec_ip_ops) "
        "with (m = 16, ef_construction = 64)"
    )
    conn.commit()
    print("vector index ready", flush=True)
