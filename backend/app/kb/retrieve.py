"""Guideline retrieval (RAG) over the knowledge database, with MedCPT.

One search:
  1. the question is encoded by the MedCPT Query Encoder, and turned into a
     keyword query (any of its words);
  2. two candidate lists: nearest passages by vector (pgvector, inner product)
     and best full-text matches (Postgres), each limited to allowed sources
     and to the sections that suit the question;
  3. the lists are fused by rank (reciprocal rank fusion, k = 60), Indian
     government and WHO/NLM sources nudged up;
  4. the MedCPT Cross-Encoder reads each (question, passage) pair and the best
     few are kept, labelled [S1], [S2] ... for citation.

Which sources a report may use: those marked production_allowed, plus
"testing" sources (ICMR STW, NFI, WHO; awaiting permission) when
`knowledge_testing_sources` is on, plus community (Hugging Face) sources only
when `knowledge_community_sources` is on.

Offline (the database unreachable), the same search runs on a snapshot of
the allowed passages saved by `python -m app.kb snapshot` (vectors and text
in data/rag_cache/), with keyword overlap in place of full-text search.
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .text import normalize, numbers, words

log = logging.getLogger("medora.kb.retrieve")

RRF_K = 60
CANDIDATES = 40  # from each list
RERANK = 16  # pairs the cross-encoder reads (each cut to 256 tokens)
# Cross-encoder scores are not calibrated across questions (2026-10-27: the
# right UTI passages scored -9.6 and -14.5, while irrelevant passages for a
# fever scored -2), so no fixed cut-off: a passage is kept when it scores
# within RERANK_WINDOW of the question's best one.
RERANK_WINDOW = 10.0
# Passages pulled in per named condition (its own guideline pages), on top of
# the RERANK best candidates: "fever with chills every other day" never reaches
# the malaria pages by its words, but "malaria" in the condition names does.
TOPIC_CANDIDATES = 3
_GENERIC = {"acute", "chronic", "uncomplicated", "complicated", "mild", "moderate", "severe", "simple",
            "probable", "suspected", "possible", "primary", "secondary", "early", "likely"}
TIER_BOOST = {1: 0.006, 2: 0.003, 3: 0.0, 4: 0.0, 5: -0.004}
# After the cross-encoder (its scores span about 10-20 points per question):
# an Indian government passage wins a close call against an international
# one, as Indian regimens differ (malaria, scabies) and the hospital is in
# India. A clearly better passage still wins.
TIER_RERANK = {1: 2.0, 2: 0.5}
EXCERPT_CHARS = 1100
MAX_LEAFLETS = 2
# After a failed connection the database is not tried again for this long:
# a report makes about ten look-ups, and each would wait its own 5 s.
RETRY_AFTER = 60.0

# What each pass looks for (kb_chunks.section).
DIAGNOSIS = "diagnosis"  # pass 1: presentation, red flags, tests, referral
TREATMENT = "treatment"  # pass 2: treatment, doses, drug safety


# Drug reference material (formulary monographs, US labels, interaction and
# dosing tables, essential-medicine lists) answers "how is it treated", never
# "what could this be". Everything else (guideline posters, patient topics)
# serves both passes; each pass only PREFERS its own kind of box.
_DRUG_REFERENCE = ("drug:", "essential_list")
_PREFERRED = {
    "diagnosis": ("suspect", "red_flags", "assessment", "investigations", "referral", "patient_summary", "community_"),
    "treatment": ("treatment", "drugs", "drug:", "discharge", "prevention", "essential_list"),
}
KIND_BOOST = 0.004  # about one rank place in the fused list


def _section_kind(section: str) -> set[str]:
    if section.startswith(_DRUG_REFERENCE):
        return {TREATMENT}
    return {DIAGNOSIS, TREATMENT}


def _preferred(section: str, kind: str) -> bool:
    return section.startswith(_PREFERRED[kind])


_SECTION_SQL = {
    DIAGNOSIS: "not (k.section like 'drug:%%' or k.section = 'essential_list')",
    TREATMENT: "true",
}


@dataclass
class Passage:
    id: int
    source: str  # source key
    source_title: str
    tier: int
    page: int | None
    breadcrumb: str
    body: str
    section: str
    allowed_in_production: bool
    score: float = 0.0
    label: str = ""
    pass_name: str = ""

    def cite(self) -> dict:
        """For the stored report (camelCase, like the rest of it)."""
        return {
            "label": self.label, "source": self.source, "sourceTitle": self.source_title, "tier": self.tier,
            "page": self.page, "breadcrumb": self.breadcrumb, "excerpt": self.body[:EXCERPT_CHARS],
            "section": self.section, "pass": self.pass_name, "score": self.score,
            "productionAllowed": self.allowed_in_production,
        }


@dataclass
class Evidence:
    """What one pass found, ready to put in a prompt."""

    passages: list[Passage] = field(default_factory=list)
    query: str = ""
    note: str = ""  # why there is nothing, when there is nothing

    def prompt(self, heading: str, most: int | None = None, chars: int = EXCERPT_CHARS) -> str:
        """The passages for a prompt; `most` and `chars` shorten it (offline,
        where the local model reads about 20 tokens a second)."""
        if not self.passages:
            return f"{heading}: none found{f' ({self.note})' if self.note else ''}."
        lines = [
            f"{heading}. Cite a passage by its label, e.g. [S1], where you rely on it. "
            "Prefer tier 1 (Indian government) sources. A dose you write must match a cited passage or be "
            "standard first-line treatment you are sure of."
        ]
        for p in self.passages[:most]:
            where = f"{p.source_title}" + (f", page {p.page}" if p.page else "")
            lines.append(f"[{p.label}] (tier {p.tier}; {where}) {p.breadcrumb}\n{p.body[:chars]}")
        return "\n\n".join(lines)


def _topic_core(name: str) -> str:
    """'Uncomplicated urinary tract infection' -> 'urinary tract infection':
    the words a guideline heading would use. Too short to be specific: ''."""
    core = " ".join(w for w in normalize(name).split() if w not in _GENERIC)
    core = re.sub(r"(infection|disease|fever)s\b", r"\1", core)
    return core if len(core) >= 4 else ""


def _vector_text(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.5f}" for x in v.tolist()) + "]"


def _keyword_query(text: str) -> str:
    """Any of the question's meaningful words, for to_tsquery."""
    stop = {"the", "and", "with", "for", "from", "that", "this", "patient", "years", "year", "old", "days", "day"}
    ws = [w for w in words(text) if len(w) > 2 and w not in stop and w.isalnum()]
    seen, out = set(), []
    for w in ws:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return " | ".join(out[:24])


class Retriever:
    """Thread-safe: one database connection, used under a lock."""

    def __init__(self, url: str, testing_sources: bool = False, community_sources: bool = False,
                 snapshot_dir: Path | None = None):
        self.url = url
        self.testing_sources = testing_sources
        self.community_sources = community_sources
        self.snapshot_dir = snapshot_dir
        self._conn = None
        self._lock = threading.Lock()
        self._snapshot = None
        self._down_until = 0.0  # monotonic time before which the database is not tried

    # --- connection -------------------------------------------------------
    def _connection(self):
        import psycopg

        if self._conn is None or self._conn.closed:
            if time.monotonic() < self._down_until:
                raise ConnectionError("the knowledge database was unreachable a moment ago")
            # A report must never wait on a stuck database: 5 s to connect,
            # 8 s per query, keepalives to notice a dropped connection. Any
            # failure falls back to the offline snapshot.
            try:
                self._conn = psycopg.connect(self.url.replace("postgresql+psycopg://", "postgresql://"),
                                             connect_timeout=5, autocommit=True, prepare_threshold=None,
                                             keepalives=1, keepalives_idle=20, keepalives_interval=5,
                                             keepalives_count=3, options="-c statement_timeout=8000")
            except Exception:
                self._down_until = time.monotonic() + RETRY_AFTER
                raise
            self._down_until = 0.0
            try:
                self._conn.execute("set hnsw.ef_search = 100")
                self._conn.execute("set hnsw.iterative_scan = relaxed_order")  # pgvector 0.8+
            except Exception:  # noqa: BLE001 - older pgvector: filtered searches may return fewer rows
                pass
        return self._conn

    def _query(self, sql: str, params: dict | tuple = ()) -> list[tuple]:
        with self._lock:
            try:
                return self._connection().execute(sql, params).fetchall()
            except Exception:
                if self._conn is not None:
                    try:
                        self._conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                self._conn = None
                raise

    def _source_filter(self) -> str:
        allowed = ["s.production_allowed"]
        if self.testing_sources:
            allowed.append("(s.tier <= 4 and not s.production_allowed)")
        if self.community_sources:
            allowed.append("s.tier = 5")
        return "(" + " or ".join(allowed) + ")" + ("" if self.community_sources else " and s.tier <= 4")

    # --- search -------------------------------------------------------------
    def warm(self) -> None:
        """Loads the three MedCPT models (about 2 s), so the first report does not."""
        from .embed import embed_queries, rerank

        try:
            embed_queries(["warm up"])
            rerank("warm up", ["warm up"])
        except Exception as e:  # noqa: BLE001
            log.warning("MedCPT models could not be loaded: %s", e)

    def search(self, question: str, kind: str, k: int = 8, topic_hint: str = "", rerank_n: int = RERANK,
               topics: list[str] | tuple[str, ...] = ()) -> Evidence:
        """The best passages for one question; `kind` is DIAGNOSIS or TREATMENT.
        `topics` (and `topic_hint`) are condition names whose own guideline
        passages join the candidates; the cross-encoder still judges every
        candidate against the question, so a topic passage that does not fit
        the patient falls out."""
        from .embed import embed_queries, rerank

        question = question.strip()
        if not question:
            return Evidence(note="no question")
        names = list(dict.fromkeys(t for t in [topic_hint, *topics] if t and t.strip()))
        qvec = embed_queries([question[:400]])[0]
        try:
            candidates = self._candidates_db(question, qvec, kind)
            extra = self._topic_candidates_db(names, qvec, kind) if names else []
        except Exception as e:  # noqa: BLE001 - offline or the database is down: use the snapshot
            log.warning("Knowledge database unreachable (%s); searching the offline snapshot", str(e)[:120])
            candidates = self._candidates_snapshot(question, qvec, kind)
            if candidates is None:
                return Evidence(query=question, note="the knowledge database could not be reached")
            extra = self._topic_candidates_snapshot(names, qvec, kind) if names else []
        top = candidates[:rerank_n]
        have = {p.id for p in top}
        top += [p for p in extra if p.id not in have and not have.add(p.id)]
        if not top:
            return Evidence(query=question, note="no matching passage")
        scores = rerank(question, [f"{p.breadcrumb}\n{p.body}" for p in top])
        for p, s in zip(top, scores):
            p.score = round(float(s) + TIER_RERANK.get(p.tier, 0.0), 2)
        top.sort(key=lambda p: p.score, reverse=True)
        best = top[0].score
        top = [p for p in top if p.score >= best - RERANK_WINDOW]
        # one passage per topic page: the best piece of it
        seen_crumbs: set[str] = set()
        top = [p for p in top if not (p.breadcrumb in seen_crumbs or seen_crumbs.add(p.breadcrumb))]
        # patient leaflets (MedlinePlus, US-centred) at most twice: they must
        # not crowd out guideline passages (Valley fever and Lyme disease
        # outranked dengue for a 2-day fever on 2026-10-27)
        leaflets = 0
        kept = []
        cores = [c for c in map(_topic_core, names) if c]
        for p in top:
            # a leaflet about a condition being looked up is not crowded out
            if p.section == "patient_summary" and not any(c in p.breadcrumb.lower() for c in cores):
                leaflets += 1
                if leaflets > MAX_LEAFLETS:
                    continue
            kept.append(p)
        top = kept
        if topic_hint:
            # prefer passages about the condition asked for, without hiding the rest
            hint = normalize(topic_hint)
            top.sort(key=lambda p: (hint not in normalize(p.breadcrumb)), reverse=False)
        return Evidence(passages=top[:k], query=question)

    def _candidates_db(self, question: str, qvec: np.ndarray, kind: str) -> list[Passage]:
        flt = self._source_filter() + " and " + _SECTION_SQL[kind]
        vec_rows = self._query(
            f"""select k.id from kb_chunks k join kb_sources s on s.id = k.source_id
                where k.embedding is not null and {flt} 
                order by k.embedding <#> %(q)s::halfvec limit {CANDIDATES}""",
            {"q": _vector_text(qvec)},
        )
        kw = _keyword_query(question)
        kw_rows = self._query(
            f"""select k.id from kb_chunks k join kb_sources s on s.id = k.source_id,
                     to_tsquery('english', %(kw)s) q
                where k.tsv @@ q and {flt}
                order by ts_rank_cd(k.tsv, q) desc limit {CANDIDATES}""",
            {"kw": kw},
        ) if kw else []
        fused: dict[int, float] = {}
        for rows in (vec_rows, kw_rows):
            for rank, (cid,) in enumerate(rows):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        if not fused:
            return []
        rows = self._query(
            """select k.id, s.key, s.title, s.tier, k.page, k.breadcrumb, k.body, k.section, s.production_allowed
               from kb_chunks k join kb_sources s on s.id = k.source_id where k.id = any(%(ids)s)""",
            {"ids": list(fused)},
        )
        passages = [Passage(*r) for r in rows]
        for p in passages:
            p.score = fused[p.id] + TIER_BOOST.get(p.tier, 0.0) + (KIND_BOOST if _preferred(p.section, kind) else 0.0)
        passages.sort(key=lambda p: p.score, reverse=True)
        return passages

    def _topic_candidates_db(self, names: list[str], qvec: np.ndarray, kind: str) -> list[Passage]:
        """Each named condition's own passages (its name in the heading): the
        pass's own kind of section first (how to suspect it for pass 1, its
        treatment for pass 2), Indian sources first, then the closest to the
        question. International passages still come through the main search."""
        flt = self._source_filter() + " and " + _SECTION_SQL[kind]
        own = " or ".join(f"k.section like '{prefix}%%'" for prefix in _PREFERRED[kind])
        out: list[Passage] = []
        for core in filter(None, map(_topic_core, names)):
            rows = self._query(
                f"""select k.id, s.key, s.title, s.tier, k.page, k.breadcrumb, k.body, k.section, s.production_allowed
                    from kb_chunks k join kb_sources s on s.id = k.source_id
                    where k.embedding is not null and {flt} and lower(k.breadcrumb) like %(p)s
                    order by ({own}) desc, s.tier, k.embedding <#> %(q)s::halfvec limit {TOPIC_CANDIDATES}""",
                {"p": f"%{core}%", "q": _vector_text(qvec)},
            )
            out += [Passage(*r) for r in rows]
        return out

    def _topic_candidates_snapshot(self, names: list[str], qvec: np.ndarray, kind: str) -> list[Passage]:
        snap = self._load_snapshot()
        if snap is None:
            return []
        vectors, meta, _ = snap
        sims = vectors @ qvec.astype(np.float32)
        out: list[Passage] = []
        for core in filter(None, map(_topic_core, names)):
            hits = [i for i, m in enumerate(meta) if core in m[5].lower() and kind in _section_kind(m[7])]
            for i in sorted(hits, key=lambda i: (not _preferred(meta[i][7], kind), meta[i][3], -sims[i]))[:TOPIC_CANDIDATES]:
                out.append(Passage(*meta[i]))
        return out

    def page_boxes(self, passage: Passage, limit: int = 12) -> list[Passage]:
        """The other boxes of the same guideline page (same source, page and
        topic). A treatment workflow splits one condition into boxes per
        patient group ("Cystitis in females", "Male UTI"); a search may find
        only one of them."""
        if passage.page is None:
            return []
        root = passage.breadcrumb.rsplit(" › ", 1)[0]
        try:
            rows = self._query(
                f"""select k.id, s.key, s.title, s.tier, k.page, k.breadcrumb, k.body, k.section, s.production_allowed
                    from kb_chunks k join kb_sources s on s.id = k.source_id
                    where s.key = %(src)s and k.page = %(page)s and k.id <> %(id)s
                      and starts_with(k.breadcrumb, %(root)s) and {self._source_filter()}
                    order by k.id limit {int(limit)}""",
                {"src": passage.source, "page": passage.page, "id": passage.id, "root": root + " › "},
            )
            return [Passage(*r) for r in rows]
        except Exception:  # noqa: BLE001 - offline: the snapshot has the same boxes
            snap = self._load_snapshot()
            if snap is None:
                return []
            return [Passage(*m) for m in snap[1]
                    if m[1] == passage.source and m[4] == passage.page and m[0] != passage.id
                    and m[5].startswith(root + " › ")][:limit]

    # --- structured look-ups ------------------------------------------------
    def drug_id(self, name: str) -> int | None:
        from .drugnames import canonical

        rows = self._query(
            """select d.id from kb_drugs d where d.normalized = %(key)s
               union all
               select d.id from kb_terms t join kb_drugs d on t.concept = 'DRUG:' || d.normalized
               where t.kind = 'drug' and t.normalized = %(n)s limit 1""",
            {"key": canonical(name), "n": normalize(name)},
        )
        return rows[0][0] if rows else None

    def doses(self, drug: str) -> list[dict]:
        """Printed doses for a medicine from the allowed sources, Indian first."""
        did = self.drug_id(drug)
        if did is None:
            return []
        rows = self._query(
            f"""select x.drug, x.indication, x.population, x.dose, x.route, x.frequency, x.duration, x.page,
                       s.title, s.tier, x.conflict from kb_doses x join kb_sources s on s.id = x.source_id
                where x.drug_id = %(d)s and {self._source_filter()} order by s.tier, x.page""",
            {"d": did},
        )
        keys = ("drug", "indication", "population", "dose", "route", "frequency", "duration", "page", "source", "tier", "conflict")
        return [dict(zip(keys, r)) for r in rows]

    def condition_doses(self, condition: str, limit: int = 8) -> list[dict]:
        """Printed doses given FOR a condition (STW pages about it, NFI entries
        whose indications name it), Indian sources first."""
        name = normalize(condition)
        generic = {"acute", "chronic", "uncomplicated", "mild", "moderate", "severe", "simple", "probable", "suspected"}
        core = " ".join(w for w in name.split() if w not in generic) or name
        if len(core) < 4:
            return []
        rows = self._query(
            f"""select x.drug, x.indication, x.population, x.dose, x.route, x.frequency, x.duration, x.page,
                       s.title, s.tier
                from kb_doses x join kb_sources s on s.id = x.source_id
                where {self._source_filter()} and lower(x.indication) like %(p)s
                order by s.tier, (s.kind = 'guideline') desc, length(x.indication) limit {int(limit)}""",
            {"p": f"%{core}%"},
        )
        keys = ("drug", "indication", "population", "dose", "route", "frequency", "duration", "page", "source", "tier")
        return [dict(zip(keys, r)) for r in rows]

    def safety(self, drug: str, kinds: tuple[str, ...] = ()) -> list[dict]:
        did = self.drug_id(drug)
        if did is None:
            return []
        rows = self._query(
            f"""select x.kind, x.body, x.page, s.title, s.tier from kb_drug_safety x join kb_sources s on s.id = x.source_id
                where x.drug_id = %(d)s and {self._source_filter()} {'and x.kind = any(%(k)s)' if kinds else ''}
                order by s.tier""",
            {"d": did, "k": list(kinds)},
        )
        return [dict(zip(("kind", "body", "page", "source", "tier"), r)) for r in rows]

    def drug_names(self) -> list[str]:
        """Every medicine name in the guideline database, loaded once (for
        the doctor's type-ahead); empty while the database is unreachable."""
        cached = getattr(self, "_drug_names", None)
        if cached is not None:
            return cached
        # Loaded in the background so a doctor's typing never waits on a
        # slow or unreachable database; the list joins once it is in.
        if not getattr(self, "_drug_names_loading", False) and time.monotonic() >= self._down_until:
            self._drug_names_loading = True

            def load() -> None:
                try:
                    rows = self._query("select distinct name from kb_drugs where name is not null")
                    self._drug_names = sorted({str(r[0]).strip() for r in rows if r[0] and len(str(r[0])) <= 80})
                except Exception:  # noqa: BLE001 - suggestions never fail for want of it
                    pass
                finally:
                    self._drug_names_loading = False

            threading.Thread(target=load, daemon=True).start()
        return []

    def brand(self, name: str) -> dict | None:
        """What a brand the patient took contains ('Dolo 650' -> paracetamol 650 mg)."""
        n = normalize(name)
        if not n:
            return None
        rows = self._query(
            """select brand, composition, composition_key from kb_drug_products
               where normalized = %(n)s or normalized like %(p)s order by length(normalized) limit 1""",
            {"n": n, "p": n + " %"},
        )
        if not rows:
            return None
        return {"brand": rows[0][0], "composition": rows[0][1], "generic": rows[0][2]}

    # --- offline snapshot ---------------------------------------------------
    def save_snapshot(self) -> int:
        """Saves the allowed, embedded passages for offline search. Runs on
        its own connection without the 8 s query limit (tens of thousands
        of vectors over a LAN take minutes), reads in batches, and replaces
        the old snapshot only once the new one is complete."""
        import psycopg

        if self.snapshot_dir is None:
            raise RuntimeError("no snapshot folder")
        rows: list[tuple] = []
        with psycopg.connect(self.url.replace("postgresql+psycopg://", "postgresql://"), connect_timeout=10,
                             keepalives=1, keepalives_idle=20, keepalives_interval=5, keepalives_count=3) as conn:
            conn.execute("set statement_timeout = 0")
            with conn.cursor(name="kb_snapshot") as cur:
                cur.itersize = 2000
                cur.execute(
                    f"""select k.id, s.key, s.title, s.tier, k.page, k.breadcrumb, k.body, k.section, s.production_allowed,
                               k.embedding::text
                        from kb_chunks k join kb_sources s on s.id = k.source_id
                        where k.embedding is not null and {self._source_filter()}"""
                )
                rows = list(cur)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        vectors = np.array([json.loads(r[9]) for r in rows], dtype=np.float16) if rows else np.zeros((0, 768), np.float16)
        meta = [list(r[:9]) for r in rows]
        tmp_vectors = self.snapshot_dir / "kb_vectors.tmp.npy"
        tmp_meta = self.snapshot_dir / "kb_passages.tmp.json"
        np.save(tmp_vectors, vectors)
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False))
        tmp_vectors.replace(self.snapshot_dir / "kb_vectors.npy")
        tmp_meta.replace(self.snapshot_dir / "kb_passages.json")
        self._snapshot = None
        return len(rows)

    def _load_snapshot(self):
        if self._snapshot is None and self.snapshot_dir and (self.snapshot_dir / "kb_vectors.npy").exists():
            vectors = np.load(self.snapshot_dir / "kb_vectors.npy").astype(np.float32)
            meta = json.loads((self.snapshot_dir / "kb_passages.json").read_text())
            terms = [set(words(m[5] + " " + m[6])) for m in meta]
            self._snapshot = (vectors, meta, terms)
        return self._snapshot

    def _candidates_snapshot(self, question: str, qvec: np.ndarray, kind: str) -> list[Passage] | None:
        snap = self._load_snapshot()
        if snap is None:
            return None
        vectors, meta, terms = snap
        allowed = np.array([kind in _section_kind(m[7]) for m in meta])
        if not allowed.any():
            return []
        sims = vectors @ qvec.astype(np.float32)
        sims[~allowed] = -np.inf
        by_vec = np.argsort(-sims)[:CANDIDATES]
        q = {w for w in words(question) if len(w) > 2}
        overlap = np.array([len(q & t) if a else -1 for t, a in zip(terms, allowed)])
        by_kw = [i for i in np.argsort(-overlap)[:CANDIDATES] if overlap[i] > 0]
        fused: dict[int, float] = {}
        for ranked in (by_vec, by_kw):
            for rank, i in enumerate(ranked):
                fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (RRF_K + rank + 1)
        passages = []
        for i, score in fused.items():
            p = Passage(*meta[i])
            p.score = score + TIER_BOOST.get(p.tier, 0.0) + (KIND_BOOST if _preferred(p.section, kind) else 0.0)
            passages.append(p)
        passages.sort(key=lambda p: p.score, reverse=True)
        return passages


def label(*evidences: Evidence) -> list[Passage]:
    """Numbers the passages of several passes [S1], [S2] ... without repeats."""
    seen: dict[int, Passage] = {}
    for ev in evidences:
        kept = []
        for p in ev.passages:
            if p.id in seen:
                kept.append(seen[p.id])
                continue
            p.label = f"S{len(seen) + 1}"
            seen[p.id] = p
            kept.append(p)
        ev.passages = kept
    return list(seen.values())


_NEW_ITEM = ("-", "*", "|", "•", "·")


def dose_found(dose_text: str, drug: str, texts: list[str]) -> bool:
    """Whether a written dose's numbers all appear next to the medicine's
    name: on the line that names it (and its continuation lines), or anywhere
    in a text whose first line (heading, breadcrumb) is about that medicine.
    "Nitrofurantoin 100 mg BD" two lines above "Ciprofloxacin 500 mg BD" is
    not evidence for ciprofloxacin 100 mg."""
    from .drugnames import canonical

    # the amount, not "(1 tablet)" or "2 tablets" beside it
    amount = re.sub(r"\([^)]*\)|\b\d+\s*(tablets?|capsules?|tabs?)\b", " ", dose_text or "", flags=re.I)
    wanted = numbers(amount) or numbers(dose_text)
    if not wanted:
        return False
    # the name as written and its shared spelling (amoxycillin = amoxicillin, acetaminophen = paracetamol)
    name_words = {w for w in words(drug) + canonical(drug).split() if len(w) > 3}

    def names(line: str) -> bool:
        return bool(name_words & (set(words(line)) | set(canonical(line).split())))

    for t in texts:
        lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
        if not lines:
            continue
        if not name_words or names(lines[0]):
            if wanted <= numbers(t):
                return True
            continue
        for i, line in enumerate(lines):
            if not names(line):
                continue
            window = [line]
            for nxt in lines[i + 1:i + 3]:
                if nxt.startswith(_NEW_ITEM):
                    break
                window.append(nxt)
            if wanted <= numbers(" ".join(window)):
                return True
    return False
