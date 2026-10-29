"""Writes a Staged result to the database, idempotently.

Loading the same file twice changes nothing the second time: names resolve to
the rows that already exist (by normalized name, then by alias), links and
precautions that are already present are skipped, and text is only filled in
where a row has none. The caller owns the transaction.
"""

from collections.abc import Iterable, Iterator

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from ..knowledge_models import (
    ENTITY_FIELDS,
    ENTITY_MODELS,
    DiseaseLink,
    IngestionReject,
    IngestionRun,
    Precaution,
)
from .transform import MAX_ALIASES, Staged, fuzzy_key, normalize

CHUNK = 2000


def _chunks(items: list, size: int = CHUNK) -> Iterator[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class _Index:
    """Existing rows of one entity table, addressable by name or alias."""

    def __init__(self, db: Session, table: str):
        self.model = ENTITY_MODELS[table]
        self.by_name: dict[str, int] = {}
        self.by_alias: dict[str, int] = {}
        self.by_fuzzy: dict[str, int] = {}
        self.rows: dict[int, dict] = {}
        columns = [self.model.id, self.model.normalized_name, self.model.aliases]
        columns += [getattr(self.model, f) for f in ENTITY_FIELDS[table]]
        for row in db.execute(select(*columns)).mappings():
            self.rows[row["id"]] = dict(row)
            self.by_name[row["normalized_name"]] = row["id"]
            self.by_fuzzy.setdefault(fuzzy_key(row["normalized_name"]), row["id"])
        for row in self.rows.values():
            for alias in row["aliases"] or []:
                self.by_alias.setdefault(normalize(alias), row["id"])

    def find(self, key: str) -> int | None:
        """The row named `key`, else the row that has it as an alias, else a
        row whose name differs only in spacing or a plural."""
        for found in (self.by_name.get(key), self.by_alias.get(key), self.by_fuzzy.get(fuzzy_key(key))):
            if found is not None:
                return found
        return None

    def free_for(self, alias_key: str, row_id: int | None) -> bool:
        """False when the alias already names, or is an alias of, another row."""
        owner = self.by_name.get(alias_key, self.by_alias.get(alias_key))
        return owner is None or owner == row_id

    def find_by_synonyms(self, keys: Iterable[str]) -> int | None:
        """The single row that any of `keys` points to. When they point to
        different rows the term is ambiguous and matches nothing: guessing
        would merge the names of two different things."""
        found = {row_id for key in keys if (row_id := self.find(key)) is not None}
        return found.pop() if len(found) == 1 else None


def apply(db: Session, staged: Staged, run_id: int) -> dict:
    stats: dict = {}
    ids: dict[str, dict[str, int]] = {}

    for table, drafts in staged.entities.items():
        if not drafts:
            ids[table] = {}
            continue
        index = _Index(db, table)
        resolved: dict[str, int] = {}
        updates: dict[int, dict] = {}
        new_rows: list[dict] = []
        # Within this file: fuzzy key -> the new row that claimed it, and
        # the drafts folded into that row.
        new_by_fuzzy: dict[str, dict] = {}
        folded: dict[str, str] = {}
        skipped = 0

        for key, draft in drafts.items():
            row_id = index.find(key)
            if row_id is None and not draft.create:
                # A dictionary term may be filed under another name than
                # ours; its synonyms can still identify our row.
                row_id = index.find_by_synonyms(draft.aliases)
            if row_id is None and not draft.create:
                skipped += 1
                continue
            if row_id is None:
                twin = new_by_fuzzy.get(fuzzy_key(key))
                if twin is not None:
                    # Same thing spelled another way earlier in this file.
                    folded[key] = twin["normalized_name"]
                    known = {normalize(a) for a in twin["aliases"]}
                    extra = [draft.name, *draft.aliases.values()]
                    twin["aliases"] += [
                        a for a in extra if normalize(a) not in known
                    ][: max(0, MAX_ALIASES - len(twin["aliases"]))]
                    for column in ENTITY_FIELDS[table]:
                        twin[column] = twin[column] or draft.text(column)
                    continue
                row = {
                    "name": draft.name,
                    "normalized_name": key,
                    "aliases": [
                        name for a, name in draft.aliases.items() if index.free_for(a, None)
                    ],
                    "created_run_id": run_id,
                    **{f: draft.text(f) for f in ENTITY_FIELDS[table]},
                }
                new_rows.append(row)
                new_by_fuzzy[fuzzy_key(key)] = row
                continue
            resolved[key] = row_id
            row = index.rows[row_id]
            change: dict = updates.get(row_id, {})
            # Fill in text the row lacks; never overwrite what is there.
            for column in ENTITY_FIELDS[table]:
                if not row[column] and not change.get(column) and (text := draft.text(column)):
                    change[column] = text
            aliases = list(change.get("aliases", row["aliases"] or []))
            known = {normalize(a) for a in aliases} | {row["normalized_name"]}
            incoming = dict(draft.aliases)
            if key != row["normalized_name"]:
                incoming[key] = draft.name  # matched through an alias
            added = [
                name
                for alias_key, name in incoming.items()
                if alias_key not in known and index.free_for(alias_key, row_id)
            ][: max(0, MAX_ALIASES - len(aliases))]
            for name in added:
                index.by_alias.setdefault(normalize(name), row_id)
            if added:
                change["aliases"] = aliases + added
            if change:
                updates[row_id] = change

        model = index.model
        for chunk in _chunks(new_rows):
            created = db.execute(
                insert(model).returning(model.id, model.normalized_name), chunk
            )
            for row_id, key in created:
                resolved[key] = row_id
        for key, twin_key in folded.items():
            resolved[key] = resolved[twin_key]
        # Rows are grouped by the columns they change: a bulk UPDATE needs
        # every parameter set to have the same keys.
        by_shape: dict[tuple, list[dict]] = {}
        for row_id, change in updates.items():
            by_shape.setdefault(tuple(sorted(change)), []).append({"id": row_id, **change})
        for rows in by_shape.values():
            for chunk in _chunks(rows):
                db.execute(update(model), chunk)

        ids[table] = resolved
        stats[table] = {"created": len(new_rows), "updated": len(updates), "not_matched": skipped}

    stats["links"] = _links(db, staged, ids, run_id)
    stats["precautions"] = _precautions(db, staged, ids, run_id)

    if staged.reject_samples:
        db.execute(
            insert(IngestionReject),
            [{"run_id": run_id, "reason": r, "value": v} for r, v in staged.reject_samples],
        )
    return stats


def _links(db: Session, staged: Staged, ids: dict, run_id: int) -> dict:
    wanted: set[tuple[int, str, int]] = set()
    for disease_key, table, other_key in staged.links:
        disease_id = ids["diseases"].get(disease_key)
        other_id = ids[table].get(other_key)
        if disease_id and other_id:
            wanted.add((disease_id, table, other_id))
    if not wanted:
        return {"created": 0, "already_present": 0}

    existing: set[tuple[int, str, int]] = set()
    for chunk in _chunks(sorted({d for d, _, _ in wanted}), 5000):
        for disease_id, symptom_id, drug_id in db.execute(
            select(DiseaseLink.disease_id, DiseaseLink.symptom_id, DiseaseLink.drug_id).where(
                DiseaseLink.disease_id.in_(chunk)
            )
        ):
            existing.add(
                (disease_id, "symptoms", symptom_id)
                if symptom_id is not None
                else (disease_id, "drugs", drug_id)
            )
    new = sorted(wanted - existing)
    for chunk in _chunks(new, 5000):
        db.execute(
            insert(DiseaseLink),
            [
                {
                    "disease_id": disease_id,
                    "symptom_id": other_id if table == "symptoms" else None,
                    "drug_id": other_id if table == "drugs" else None,
                    "run_id": run_id,
                }
                for disease_id, table, other_id in chunk
            ],
        )
    return {"created": len(new), "already_present": len(wanted) - len(new)}


def _precautions(db: Session, staged: Staged, ids: dict, run_id: int) -> dict:
    wanted: set[tuple[int | None, int | None, str]] = set()
    for disease_key, symptom_key, text in staged.precautions:
        disease_id = ids["diseases"].get(disease_key) if disease_key else None
        symptom_id = ids["symptoms"].get(symptom_key) if symptom_key else None
        if disease_id or symptom_id:
            wanted.add((disease_id, symptom_id, text))
    if not wanted:
        return {"created": 0, "already_present": 0}

    existing: set[tuple[int | None, int | None, str]] = set()
    disease_ids = sorted({d for d, _, _ in wanted if d})
    symptom_ids = sorted({s for _, s, _ in wanted if s})
    for column, values in ((Precaution.disease_id, disease_ids), (Precaution.symptom_id, symptom_ids)):
        for chunk in _chunks(values, 5000):
            for row in db.execute(
                select(Precaution.disease_id, Precaution.symptom_id, Precaution.precaution).where(
                    column.in_(chunk)
                )
            ):
                existing.add((row[0], row[1], normalize(row[2])))
    new = sorted(
        (w for w in wanted if (w[0], w[1], normalize(w[2])) not in existing),
        key=lambda w: (w[0] or 0, w[1] or 0, w[2]),
    )
    for chunk in _chunks(new, 5000):
        db.execute(
            insert(Precaution),
            [
                {"disease_id": d, "symptom_id": s, "precaution": text, "run_id": run_id}
                for d, s, text in chunk
            ],
        )
    return {"created": len(new), "already_present": len(wanted) - len(new)}


def undo(db: Session, run_id: int) -> dict:
    """Removes what a run added. Text and aliases it merged into rows created
    by other runs stay, since they cannot be told apart afterwards."""
    stats = {
        "links": db.execute(delete(DiseaseLink).where(DiseaseLink.run_id == run_id)).rowcount,
        "precautions": db.execute(delete(Precaution).where(Precaution.run_id == run_id)).rowcount,
    }
    # A row made by this run can outlive it while another run's links use it.
    # So rows made by any undone run are swept too: once the last run using
    # them is undone, in whatever order, they go.
    makers = select(IngestionRun.id).where(
        (IngestionRun.status == "undone") | (IngestionRun.id == run_id)
    )
    # Symptoms and drugs first: a disease may only go once nothing points at it.
    for table in ("symptoms", "drugs", "diseases"):
        model = ENTITY_MODELS[table]
        link_column = {
            "symptoms": DiseaseLink.symptom_id,
            "drugs": DiseaseLink.drug_id,
            "diseases": DiseaseLink.disease_id,
        }[table]
        still_used = select(link_column).where(link_column.is_not(None))
        condition = model.created_run_id.in_(makers) & model.id.not_in(still_used)
        if table != "drugs":
            precaution_column = (
                Precaution.symptom_id if table == "symptoms" else Precaution.disease_id
            )
            condition &= model.id.not_in(
                select(precaution_column).where(precaution_column.is_not(None))
            )
        stats[table] = db.execute(delete(model).where(condition)).rowcount
    db.execute(delete(IngestionReject).where(IngestionReject.run_id == run_id))
    return stats
