"""Applies a Plan to records: clean, validate, de-duplicate, stage.

Nothing here touches the database. The result is a `Staged` object that says
exactly what a load would write and what was refused, so the same code serves
previews and real loads.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..knowledge_models import ENTITY_FIELDS
from .plan import Col, EntityOutput, LinkOutput, Plan, PrecautionOutput
from .records import Record, get_values

# Longest name each table accepts, in characters and words. Anything longer
# is a sentence that was mistaken for a name.
NAME_LIMITS = {"diseases": (120, 14), "symptoms": (80, 9), "drugs": (120, 14)}
TEXT_LIMIT = 2000
PRECAUTION_LIMITS = (8, 300)
MAX_ALIASES = 25
# More symptoms than this against one "disease" in a single file means the
# row is not a disease: hand-merged sources contain reversed rows, with a
# symptom ("Pain", "Fever") in the disease column and hundreds of conditions
# listed as its symptoms. Real diseases in the data stay below about 70.
MAX_SYMPTOMS_PER_DISEASE = 120
REJECT_SAMPLES_PER_REASON = 20

_PLACEHOLDERS = {
    "na", "n a", "none", "null", "nil", "unknown", "nan", "not available",
    "not applicable", "other", "others", "all", "various", "tbd", "test",
}  # fmt: skip


# A class of medicines ("antibiotics", "beta blockers") is not a medicine.
_DRUG_CLASS = re.compile(
    r"\b(agents?|agonists?|antagonists?|inhibitors?|blockers?|corticosteroids|steroids|"
    r"antibiotics|antivirals|antifungals|antipsychotics|antidepressants|anticoagulants|"
    r"anticonvulsants|antihistamines|bronchodilators|diuretics|opioids|nsaids|statins|"
    r"analgesics|sedatives|immunosuppressants|medications?|medicines?|drugs?|therapy|"
    r"therapies|treatments?)$"
)


# Windows-1252 punctuation that survives as control characters in files
# decoded with the wrong codec.
_CP1252 = str.maketrans({0x91: "'", 0x92: "'", 0x93: '"', 0x94: '"', 0x96: "-", 0x97: "-"})
_APOSTROPHES = str.maketrans("", "", "'’‘`´")


def normalize(name: str) -> str:
    """The matching key: case, accents, punctuation and spacing do not count.

    Apostrophes vanish ("Crohn's" = "Crohns"); every other punctuation mark,
    including any kind of dash, becomes a space.
    """
    text = unicodedata.normalize("NFKD", name.translate(_CP1252).translate(_APOSTROPHES))
    chars = []
    for ch in text.casefold():
        if unicodedata.combining(ch):
            continue
        chars.append(ch if ch.isascii() and ch.isalnum() else " ")
    return " ".join("".join(chars).split())


def fuzzy_key(key: str) -> str:
    """A looser key for a second matching pass: spacing and a plural "s" do
    not count, so "Chicken pox" = "Chickenpox" and "Headaches" = "Headache"."""
    squashed = key.replace(" ", "")
    if len(squashed) > 4 and squashed.endswith("s") and not squashed.endswith(("ss", "us", "is")):
        squashed = squashed[:-1]
    return squashed


def _is_variant_of(alias_key: str, key: str) -> bool:
    """True when one name is the other plus extra words: a subtype, a broader
    term or a product variant ("Retinal migraine" for "Migraine"), which is
    not another name for the same thing."""
    a, b = f" {alias_key} ", f" {key} "
    return a != b and (a in b or b in a)


def clean_name(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw.translate(_CP1252)).replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip(" \t,;:.-–—\"'")
    # Sources shout or whisper; store one readable form. Mixed case is kept,
    # since it usually carries meaning ("Crohn's disease"), and so are
    # abbreviations ("HIV/AIDS", "COVID-19", "COPD").
    abbreviation = len(text) <= 5 or (" " not in text and re.search(r"[/\d-]", text))
    if text.isupper() and not abbreviation:
        text = text[0] + text[1:].lower()
    elif text.islower():
        text = text[0].upper() + text[1:]
    return text


def clean_text(raw: str, limit: int = TEXT_LIMIT) -> str:
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", raw)).strip()
    # Label documents repeat their section heading in the body
    # ("1 INDICATIONS AND USAGE Drug X is ..."); drop it.
    text = re.sub(
        r"^(?:\d+(?:\.\d+)*\s+(?:[A-Z][A-Z&/,-]*\s+){1,8}|(?:[A-Z][A-Z&/,-]+\s+){2,8})(?=\(|[A-Z][a-z])",
        "",
        text,
    )
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Prefer ending on a whole sentence over an arbitrary cut.
    end = max(cut.rfind(". "), cut.rfind("; "))
    return cut[: end + 1] if end > limit * 0.5 else cut.rstrip() + "…"


def check_name(table: str, name: str) -> str | None:
    """Why `name` cannot be a row in `table`, or None when it can."""
    max_chars, max_words = NAME_LIMITS[table]
    key = normalize(name)
    if len(key) < 2:
        return "name_too_short"
    if not re.search(r"[a-z]", key):
        return "name_has_no_letters"
    if key in _PLACEHOLDERS:
        return "name_is_placeholder"
    if len(name) > max_chars or len(key.split()) > max_words:
        return "name_is_a_sentence"
    if table == "drugs" and _DRUG_CLASS.search(key):
        return "name_is_a_drug_class"
    return None


@dataclass
class EntityDraft:
    name: str
    aliases: dict[str, str] = field(default_factory=dict)  # key -> display
    # Distinct text pieces per field, in the order seen.
    fields: dict[str, list[str]] = field(default_factory=dict)
    create: bool = True

    def text(self, column: str) -> str:
        return clean_text(" ".join(self.fields.get(column, [])))


@dataclass
class Staged:
    records: int = 0
    # table -> normalized name -> draft
    entities: dict[str, dict[str, EntityDraft]] = field(
        default_factory=lambda: {t: {} for t in ENTITY_FIELDS}
    )
    # (disease key, "symptoms" | "drugs", other key)
    links: set[tuple[str, str, str]] = field(default_factory=set)
    # (disease key or "", symptom key or "", text)
    precautions: set[tuple[str, str, str]] = field(default_factory=set)
    accepted: int = 0
    rejected: Counter = field(default_factory=Counter)
    reject_samples: list[tuple[str, str]] = field(default_factory=list)

    def reject(self, reason: str, value: str) -> None:
        self.rejected[reason] += 1
        if self.rejected[reason] <= REJECT_SAMPLES_PER_REASON:
            self.reject_samples.append((reason, value[:300]))

    @property
    def reject_rate(self) -> float:
        """Share of names and precautions refused. Dropped aliases are
        reported but do not count: losing an alias loses no row."""
        refused = sum(n for reason, n in self.rejected.items() if "alias" not in reason)
        total = self.accepted + refused
        return refused / total if total else 0.0

    def summary(self) -> dict:
        return {
            "records": self.records,
            "diseases": len(self.entities["diseases"]),
            "symptoms": len(self.entities["symptoms"]),
            "drugs": len(self.entities["drugs"]),
            "links": len(self.links),
            "precautions": len(self.precautions),
            "values_accepted": self.accepted,
            "values_rejected": dict(self.rejected),
            "reject_rate": round(self.reject_rate, 4),
        }

    # --- staging helpers --------------------------------------------------

    def entity(self, table: str, raw: str, create: bool = True) -> str | None:
        """Stages a name and returns its key, or None when it is refused."""
        # "Urinary tract infection (UTI)" is the disease "Urinary tract
        # infection" with the alias "UTI", not a second disease.
        bracket = re.match(r"^(.{3,}?)\s*\(([^()]{2,60})\)\s*$", raw.strip())
        if bracket:
            key = self.entity(table, bracket.group(1), create)
            if key is not None:
                self.alias(table, key, bracket.group(2))
            return key
        name = clean_name(raw)
        problem = check_name(table, name)
        if problem:
            self.reject(f"{table}:{problem}", raw)
            return None
        key = normalize(name)
        draft = self.entities[table].get(key)
        if draft is None:
            self.entities[table][key] = EntityDraft(name=name, create=create)
        elif create:
            draft.create = True
        self.accepted += 1
        return key

    def alias(self, table: str, key: str, raw: str) -> None:
        name = clean_name(raw)
        alias_key = normalize(name)
        draft = self.entities[table][key]
        if (
            alias_key != key
            and check_name(table, name) is None
            and not _is_variant_of(alias_key, key)
            and len(draft.aliases) < MAX_ALIASES
        ):
            draft.aliases.setdefault(alias_key, name)

    def add_text(self, table: str, key: str, column: str, raw: str) -> None:
        pieces = self.entities[table][key].fields.setdefault(column, [])
        # Sentence-sized pieces from several rows are joined into one text.
        # A piece that is already a full passage stands alone: appending the
        # same section from another product's label would only repeat it.
        if pieces and (len(pieces[0]) >= 400 or sum(map(len, pieces)) >= TEXT_LIMIT):
            return
        text = clean_text(raw)
        if text and text not in pieces:
            pieces.append(text)

    def drop_implausible_diseases(self) -> None:
        """Removes "diseases" with an impossible number of symptoms, and the
        symptoms that only they referred to (see MAX_SYMPTOMS_PER_DISEASE)."""
        counts: Counter = Counter(d for d, table, _ in self.links if table == "symptoms")
        bad = {d for d, n in counts.items() if n > MAX_SYMPTOMS_PER_DISEASE}
        if not bad:
            return
        removed = {link for link in self.links if link[0] in bad and link[1] == "symptoms"}
        self.links -= removed
        still_linked = {d for d, _, _ in self.links} | {d for d, _, _ in self.precautions}
        for key in bad:
            draft = self.entities["diseases"][key]
            self.reject("diseases:too_many_symptoms_to_be_a_disease", draft.name)
            # A bare name with nothing attached is not worth a row.
            if key not in still_linked and not any(draft.fields.values()):
                del self.entities["diseases"][key]
        used = {other for _, table, other in self.links if table == "symptoms"}
        used |= {s for _, s, _ in self.precautions}
        for key in {other for _, _, other in removed} - used:
            draft = self.entities["symptoms"][key]
            if not any(draft.fields.values()) and not draft.aliases:
                del self.entities["symptoms"][key]

    def drop_ambiguous_aliases(self) -> None:
        """An alias must identify one row. A name that several rows claim
        ("Pain relief" as a brand of many drugs), or that is itself the name
        of another row, identifies none and is removed everywhere."""
        for table, drafts in self.entities.items():
            claims: Counter = Counter(a for d in drafts.values() for a in d.aliases)
            dropped = 0
            for draft in drafts.values():
                for alias_key in [a for a in draft.aliases if claims[a] > 1 or a in drafts]:
                    del draft.aliases[alias_key]
                    dropped += 1
            if dropped:
                self.rejected[f"{table}:alias_is_ambiguous"] += dropped

    def precaution(self, disease_key: str, symptom_key: str, raw: str) -> None:
        text = clean_text(raw, PRECAUTION_LIMITS[1] + 1)
        if not PRECAUTION_LIMITS[0] <= len(text) <= PRECAUTION_LIMITS[1]:
            self.reject("precaution:bad_length", raw)
            return
        text = text[0].upper() + text[1:]
        self.precautions.add((disease_key, symptom_key, text))
        self.accepted += 1


def _values(record: Record, col: Col | None) -> list[str]:
    if col is None:
        return []
    for source in col.sources:
        values = get_values(record, source)
        if values:
            break
    else:
        return []
    if col.split:
        values = [part for value in values for part in value.split(col.split)]
    return [v.strip() for v in values if v.strip()]


def _first(record: Record, col: Col | None) -> str:
    values = _values(record, col)
    return values[0] if values else ""


def apply_plan(plan: Plan, records: Iterable[Record], limit: int | None = None) -> Staged:
    staged = Staged()
    for record in records:
        if limit is not None and staged.records >= limit:
            break
        staged.records += 1
        for output in plan.outputs:
            if isinstance(output, EntityOutput):
                _entity(staged, output, record)
            elif isinstance(output, LinkOutput):
                _link(staged, output, record)
            elif isinstance(output, PrecautionOutput):
                _precaution(staged, output, record)
    staged.drop_implausible_diseases()
    staged.drop_ambiguous_aliases()
    return staged


def _entity(staged: Staged, output: EntityOutput, record: Record) -> None:
    raw = _first(record, output.name)
    if not raw:
        return
    key = staged.entity(output.table, raw, create=output.mode == "upsert")
    if key is None:
        return
    for alias in _values(record, output.aliases):
        staged.alias(output.table, key, alias)
    for column, col in output.fields.items():
        for value in _values(record, col):
            staged.add_text(output.table, key, column, value)


def _link(staged: Staged, output: LinkOutput, record: Record) -> None:
    disease_raw = _first(record, output.disease)
    table, col = ("symptoms", output.symptom) if output.symptom else ("drugs", output.drug)
    targets = _values(record, col)
    if not disease_raw or not targets:
        return
    disease_key = staged.entity("diseases", disease_raw)
    if disease_key is None:
        return
    for target in targets:
        key = staged.entity(table, target)
        if key is not None:
            staged.links.add((disease_key, table, key))


def _precaution(staged: Staged, output: PrecautionOutput, record: Record) -> None:
    texts = _values(record, output.text)
    if not texts:
        return
    disease_key = symptom_key = ""
    if output.disease and (raw := _first(record, output.disease)):
        disease_key = staged.entity("diseases", raw) or ""
    if output.symptom and (raw := _first(record, output.symptom)):
        symptom_key = staged.entity("symptoms", raw) or ""
    if not disease_key and not symptom_key:
        return
    for text in texts:
        staged.precaution(disease_key, symptom_key, text)
