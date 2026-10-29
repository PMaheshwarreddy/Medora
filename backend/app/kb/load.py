"""Writes what a reader produced into the knowledge database.

A source is loaded in ONE transaction: its earlier rows are removed and the
new ones written, so a re-run gives the same result and a failure leaves the
previous load in place. Embeddings of passages whose text did not change are
kept, so a reload does not recompute them.
"""

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from .sources import Source
from .drugnames import canonical, spellings
from .text import chunk, content_hash, count_tokens, normalize

log = logging.getLogger("medora.kb")

SCHEMA = Path(__file__).with_name("schema.sql")

# Tables whose rows belong to one source (deleted and rewritten on reload).
OWNED = (
    "kb_pages", "kb_terms", "kb_codes", "kb_chunks", "kb_doses", "kb_drug_safety", "kb_red_flags",
    "kb_patient_topics", "kb_drug_products", "kb_disease_symptoms", "kb_quarantine",
)
# The columns of kb_drugs each source fills (cleared on its reload).
DRUG_COLUMNS = {
    "nfi-2011": ("drug_class", "schedule", "pregnancy_category", "nfi_page"),
    "nlem-2022": ("nlem",),
    "who-eml-2025": ("who_eml",),
}

COLUMNS = {
    "kb_pages": ("page", "page_kind", "title", "markdown", "checks", "status"),
    "kb_terms": ("kind", "concept", "term", "normalized", "preferred", "umls"),
    "kb_codes": ("system", "code", "title", "parent", "billable"),
    "kb_chunks": ("page", "section", "topic", "breadcrumb", "body", "tokens", "content_hash", "embedding"),
    "kb_doses": ("page", "drug", "indication", "population", "dose", "route", "frequency", "duration", "chunk_hash"),
    "kb_drug_safety": ("page", "drug", "kind", "body"),
    "kb_red_flags": ("page", "topic", "sign", "action"),
    "kb_patient_topics": ("title", "normalized", "also_called", "summary", "url"),
    "kb_drug_products": ("brand", "normalized", "composition", "form", "manufacturer", "uses", "side_effects", "pack",
                         "price_inr", "substitutes", "composition_key"),
    "kb_disease_symptoms": ("disease", "normalized", "symptom", "symptom_normalized"),
    "kb_quarantine": ("page", "item", "reason"),
    "kb_conditions": ("doid", "name", "normalized", "definition", "parents", "icd10cm", "icd11", "mesh", "umls"),
}


def connect(url: str) -> psycopg.Connection:
    if not url:
        raise SystemExit("MEDORA_KNOWLEDGE_DATABASE_URL is not set in backend/.env")
    # TCP keepalives: a connection the network dropped is noticed within a
    # minute instead of hanging forever (an embedding run hung 43 minutes on
    # 2026-10-27 before this).
    return psycopg.connect(
        url.replace("postgresql+psycopg://", "postgresql://"), connect_timeout=15, prepare_threshold=None,
        keepalives=1, keepalives_idle=20, keepalives_interval=10, keepalives_count=3,
    )


def init_schema(conn: psycopg.Connection) -> None:
    """Creates the tables (safe to repeat). On a company server the Medora
    user may not be allowed to create extensions: then the two extensions
    must already exist, and the message says what the admin has to run."""
    sql = SCHEMA.read_text()
    for ext in ("vector", "pg_trgm"):
        try:
            conn.execute(f"create extension if not exists {ext}")
            conn.commit()
        except psycopg.Error as e:
            conn.rollback()
            have = conn.execute("select 1 from pg_extension where extname = %s", (ext,)).fetchone()
            if not have:
                raise SystemExit(
                    f"The database has no '{ext}' extension and this user may not create it ({e.diag.message_primary}). "
                    f"Ask the server admin to run, in this database: create extension {ext};"
                    + (" (pgvector 0.7 or newer must be installed on the server first)" if ext == "vector" else "")
                ) from e
    version = conn.execute("select extversion from pg_extension where extname = 'vector'").fetchone()[0]
    if tuple(int(x) for x in version.split(".")[:2]) < (0, 7):
        raise SystemExit(f"pgvector {version} is too old: 0.7 or newer is needed (halfvec). Ask the admin to upgrade it.")
    sql = "\n".join(line for line in sql.splitlines() if not line.startswith("create extension"))
    conn.execute(sql)
    conn.commit()


@dataclass
class Bundle:
    """Everything one source produced, by table."""

    rows: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    drugs: dict[str, dict] = field(default_factory=dict)  # normalized name -> columns
    stats: Counter = field(default_factory=Counter)

    def add(self, table: str, **row) -> None:
        self.rows[table].append(row)
        self.stats[table] += 1

    def refuse(self, item: dict, reason: str, page: int | None = None) -> None:
        self.add("kb_quarantine", page=page, item=item, reason=reason)

    def drug(self, name: str, **columns) -> str:
        """Adds or updates a medicine under its shared key; every spelling becomes a drug term."""
        key = canonical(name)
        if key:
            entry = self.drugs.setdefault(key, {"name": name.strip()})
            entry.update({k: v for k, v in columns.items() if v not in (None, "", [])})
            self.drug_terms(name, key)
        return key

    def drug_terms(self, name: str, key: str | None = None) -> None:
        key = key or canonical(name)
        seen = self.__dict__.setdefault("_drug_terms", set())
        for i, spelling in enumerate(spellings(name)):
            n = normalize(spelling)
            if n and (key, n) not in seen:
                seen.add((key, n))
                self.add("kb_terms", kind="drug", concept=f"DRUG:{key}", term=spelling, normalized=n, preferred=False, umls="")

    def passages(self, *, breadcrumb: str, body: str, section: str, topic: str, page: int | None = None) -> list[str]:
        """Adds a section as one or more passages; returns their hashes."""
        hashes = []
        for piece in chunk(body, breadcrumb):
            h = content_hash(breadcrumb, piece)
            seen = self.__dict__.setdefault("_chunk_hashes", set())
            if h in seen:
                self.stats["repeated passages skipped"] += 1
                continue
            seen.add(h)
            self.add(
                "kb_chunks", page=page, section=section, topic=topic, breadcrumb=breadcrumb, body=piece,
                tokens=count_tokens(breadcrumb + "\n" + piece), content_hash=h, embedding=None,
            )
            hashes.append(h)
        return hashes


def _value(v):
    if isinstance(v, dict) or (isinstance(v, list) and v and isinstance(v[0], dict)):
        return Jsonb(v)
    return v


def load(conn: psycopg.Connection, source: Source, bundle: Bundle, files: list[dict]) -> dict:
    stats = dict(bundle.stats)
    # A reader may have queried the database, which opens a transaction; end it
    # so the block below is a real transaction and not a savepoint that is
    # silently rolled back when the process exits.
    conn.commit()
    with conn.transaction():
        sid = conn.execute(
            """insert into kb_sources (key, title, publisher, edition, kind, tier, licence, licence_note, production_allowed, files, status)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'loading')
               on conflict (key) do update set title=excluded.title, publisher=excluded.publisher, edition=excluded.edition,
                 kind=excluded.kind, tier=excluded.tier, licence=excluded.licence, licence_note=excluded.licence_note,
                 production_allowed=excluded.production_allowed, files=excluded.files, status='loading'
               returning id""",
            (source.key, source.title, source.publisher, source.edition, source.kind, source.tier, source.licence,
             source.licence_note, source.production_allowed, Jsonb(files)),
        ).fetchone()[0]
        kept = dict(conn.execute(
            "select content_hash, embedding::text from kb_chunks where source_id=%s and embedding is not null", (sid,)
        ).fetchall())
        for table in OWNED:
            conn.execute(f"delete from {table} where source_id=%s", (sid,))
        if bundle.rows.get("kb_conditions"):
            conn.execute("delete from kb_conditions where source_id=%s", (sid,))
        cols = DRUG_COLUMNS.get(source.key, ())
        sets = ", ".join(f"{c}=null" if c in ("nfi_page", "nlem", "who_eml") else f"{c}=''" for c in cols)
        conn.execute(
            f"update kb_drugs set sources=array_remove(sources, %s){', ' + sets if sets else ''} where %s = any(sources)",
            (source.key, source.key),
        )
        conn.execute("delete from kb_drugs where sources = '{}'")

        for key, entry in bundle.drugs.items():
            data = {c: entry[c] for c in cols if c in entry}
            names = ["name", "normalized", "sources", *data]
            values = [entry["name"], key, [source.key], *(_value(v) for v in data.values())]
            updates = ", ".join(f"{c}=excluded.{c}" for c in data)
            conn.execute(
                f"""insert into kb_drugs ({', '.join(names)}) values ({', '.join(['%s'] * len(names))})
                    on conflict (normalized) do update set sources = array_append(array_remove(kb_drugs.sources, %s), %s)
                    {', ' + updates if updates else ''}""",
                (*values, source.key, source.key),
            )

        for h, row in ((r["content_hash"], r) for r in bundle.rows.get("kb_chunks", [])):
            if h in kept:
                row["embedding"] = kept[h]
        for table in ("kb_conditions", *OWNED):
            rows = bundle.rows.get(table)
            if not rows:
                continue
            columns = COLUMNS[table]
            with conn.cursor().copy(
                f"copy {table} (source_id, {', '.join(columns)}) from stdin"
            ) as cp:
                for row in rows:
                    cp.write_row([sid, *(_copy_value(row.get(c)) for c in columns)])
        conn.execute(
            "update kb_sources set status='loaded', stats=%s, loaded_at=now() where id=%s", (Jsonb(stats), sid)
        )
    conn.commit()
    if not conn.execute("select 1 from kb_sources where key=%s and status='loaded'", (source.key,)).fetchone():
        raise RuntimeError("the load did not persist")
    conn.commit()
    return stats


def _copy_value(v):
    if isinstance(v, (dict, list)) and (isinstance(v, dict) or (v and isinstance(v[0], dict))):
        return json.dumps(v, ensure_ascii=False)
    return v


def mark_failed(conn: psycopg.Connection, source: Source, error: str) -> None:
    conn.rollback()
    conn.execute(
        """insert into kb_sources (key, title, publisher, kind, tier, licence, status, stats)
           values (%s,%s,%s,%s,%s,%s,'failed',%s)
           on conflict (key) do update set status='failed', stats=kb_sources.stats || excluded.stats""",
        (source.key, source.title, source.publisher, source.kind, source.tier, source.licence, Jsonb({"error": error[:500]})),
    )
    conn.commit()


LINK_SQL = """
-- conditions <- terms of every vocabulary (by concept, then by cross-references)
update kb_terms t set condition_id = c.id from kb_conditions c
  where t.condition_id is null and t.concept = c.doid;
update kb_terms t set condition_id = c.id from kb_conditions c
  where t.condition_id is null and t.concept like 'MESH:%' and substr(t.concept, 6) = any(c.mesh);
update kb_terms t set condition_id = c.id from kb_conditions c
  where t.condition_id is null and t.umls <> '' and t.umls = any(c.umls);
-- passages, red flags, doses and patient topics <- conditions, by name or synonym
with names as (
  select distinct on (normalized) normalized, condition_id from kb_terms
  where kind = 'condition' and condition_id is not null order by normalized, preferred desc)
update kb_chunks k set condition_id = n.condition_id from names n
  where k.condition_id is null and k.topic <> '' and lower(regexp_replace(k.topic, '[^A-Za-z0-9]+', ' ', 'g')) = n.normalized;
with names as (
  select distinct on (normalized) normalized, condition_id from kb_terms
  where kind = 'condition' and condition_id is not null order by normalized, preferred desc)
update kb_red_flags r set condition_id = n.condition_id from names n
  where r.condition_id is null and lower(regexp_replace(r.topic, '[^A-Za-z0-9]+', ' ', 'g')) = n.normalized;
with names as (
  select distinct on (normalized) normalized, condition_id from kb_terms
  where kind = 'condition' and condition_id is not null order by normalized, preferred desc)
update kb_patient_topics p set condition_id = n.condition_id from names n
  where p.condition_id is null and p.normalized = n.normalized;
-- drugs, through every spelling any source printed (DRUG:<key> terms)
create temp table drug_names on commit drop as
  select distinct on (t.normalized) t.normalized, d.id from kb_terms t
  join kb_drugs d on t.concept = 'DRUG:' || d.normalized where t.kind = 'drug' order by t.normalized, d.id;
insert into drug_names select d.normalized, d.id from kb_drugs d
  where not exists (select 1 from drug_names n where n.normalized = d.normalized);
update kb_chunks k set drug_id = n.id from drug_names n
  where k.drug_id is null and k.section like 'drug:%' and trim(lower(regexp_replace(k.topic, '[^A-Za-z0-9]+', ' ', 'g'))) = n.normalized;
update kb_doses x set drug_id = n.id from drug_names n
  where x.drug_id is null and trim(lower(regexp_replace(x.drug, '[^A-Za-z0-9]+', ' ', 'g'))) = n.normalized;
update kb_drug_safety x set drug_id = n.id from drug_names n
  where x.drug_id is null and trim(lower(regexp_replace(x.drug, '[^A-Za-z0-9]+', ' ', 'g'))) = n.normalized;
-- brands -> medicines (by their composition), disease lists -> conditions and symptoms
update kb_drug_products p set drug_id = n.id from drug_names n
  where p.drug_id is null and p.composition_key <> '' and p.composition_key = n.normalized;
with names as (
  select distinct on (normalized) normalized, condition_id from kb_terms
  where kind = 'condition' and condition_id is not null order by normalized, preferred desc)
update kb_disease_symptoms x set condition_id = n.condition_id from names n
  where x.condition_id is null and x.normalized = n.normalized;
with s as (
  select distinct on (normalized) normalized, concept from kb_terms where kind = 'symptom' order by normalized, preferred desc)
update kb_disease_symptoms x set symptom_concept = s.concept from s
  where x.symptom_concept = '' and x.symptom_normalized = s.normalized;
-- names from lists that only print a name: attach to the condition with that name
update kb_terms t set condition_id = d.condition_id from (
  select distinct on (normalized) normalized, condition_id from kb_terms
  where kind = 'condition' and condition_id is not null order by normalized, preferred desc) d
  where t.condition_id is null and t.kind = 'condition' and t.normalized = d.normalized;
-- the same drug and indication with different doses in two sources: the doctor decides
update kb_doses x set conflict = exists (
  select 1 from kb_doses y where y.drug_id = x.drug_id and y.source_id <> x.source_id
    and y.population = x.population and y.indication <> '' and lower(y.indication) = lower(x.indication)
    and lower(regexp_replace(y.dose, '\\s', '', 'g')) <> lower(regexp_replace(x.dose, '\\s', '', 'g')))
  where x.drug_id is not null;
"""


def link(conn: psycopg.Connection) -> dict:
    """Connects rows across sources (conditions, drugs) after loading."""
    conn.execute(LINK_SQL)
    conn.commit()
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "terms_linked_to_conditions": q("select count(*) from kb_terms where condition_id is not null"),
        "passages_linked_to_conditions": q("select count(*) from kb_chunks where condition_id is not null"),
        "passages_linked_to_drugs": q("select count(*) from kb_chunks where drug_id is not null"),
        "doses_linked_to_drugs": q("select count(*) from kb_doses where drug_id is not null"),
        "dose_conflicts": q("select count(*) from kb_doses where conflict"),
        "brands_linked_to_medicines": q("select count(*) from kb_drug_products where drug_id is not null"),
        "disease_lists_linked_to_conditions": q("select count(*) from kb_disease_symptoms where condition_id is not null"),
        "disease_list_symptoms_known": q("select count(*) from kb_disease_symptoms where symptom_concept <> ''"),
    }
