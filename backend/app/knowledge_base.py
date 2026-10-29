"""Retrieval over the medical knowledge (the "R" of the report's RAG).

Given the symptoms a patient described, in whatever words, this finds the
matching symptom rows, follows the disease links, and scores each candidate
disease by the evidence for it. It is deterministic and needs no language
model, so the same evidence is available online and offline.

  1. Symptom matching: exact name, alias or spelling variant first; then
     meaning, by embedding similarity ("my head is pounding" -> Headache).
  2. Evidence scoring: a candidate is scored by how much of the patient's
     presentation it explains, weighting rare symptoms above common ones.
  3. For the best candidates: description, linked drugs and precautions.
"""

import hashlib
import logging
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from .ingest.transform import fuzzy_key, normalize
from .knowledge_models import Disease, DiseaseLink, Drug, Precaution, Symptom

log = logging.getLogger("medora.knowledge")

# A "disease" linked to more symptoms than this is not a disease: the source
# files contain reversed rows where a symptom ("Pain", "Fever") sits in the
# disease column with hundreds of conditions listed against it. Real diseases
# in the data have at most about 70 symptoms.
MAX_SYMPTOMS_PER_DISEASE = 90
# Cosine similarity a phrase needs to count as meaning a symptom.
MIN_SIMILARITY = 0.68
# The knowledge base often holds the same symptom under several names
# ("Dysuria", "Burning sensation during urination"), each linked to different
# diseases. Near-identical neighbours above this are all taken.
SYNONYM_SIMILARITY = 0.82
MAX_NEIGHBOURS = 3
MAX_CANDIDATES = 8
# Listed as drugs in the sources, but in advice to a patient they are just
# words: "drink plenty of water" must not be mistaken for naming a medicine.
_EVERYDAY_SUBSTANCES = {
    "water", "oxygen", "alcohol", "ethanol", "caffeine", "nicotine", "calcium", "magnesium",
    "iodine", "fluoride", "sulfur", "glycerin", "menthol", "camphor",
}  # fmt: skip


class Embedder:
    """Sentence embeddings from the local Ollama server (works offline)."""

    def __init__(self, url: str, model: str):
        self._url = url.rstrip("/")
        self.model = model

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=300) as client:
            for start in range(0, len(texts), 256):
                response = client.post(
                    f"{self._url}/api/embed",
                    json={"model": self.model, "input": texts[start : start + 256]},
                )
                response.raise_for_status()
                vectors += response.json()["embeddings"]
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms == 0, 1, norms)


@dataclass
class SymptomMatch:
    phrase: str  # what the patient said
    symptom_id: int
    name: str  # the knowledge-base symptom it was matched to
    score: float  # 1.0 for a name match, the similarity otherwise
    how: str  # "name" | "meaning"
    # Which of the patient's symptoms this belongs to: several knowledge-base
    # rows matched for one complaint count as one piece of evidence.
    group: int = 0


@dataclass
class Candidate:
    disease_id: int
    name: str
    score: float  # 0..1 evidence score
    matched: list[str]  # the patient's symptoms this disease explains
    symptom_count: int  # how many symptoms the disease has in total
    description: str = ""
    causes: str = ""
    drugs: list[dict] = field(default_factory=list)  # {"name", "uses"}
    precautions: list[str] = field(default_factory=list)
    # Other names of the disease ("scabies" for Acariasis), normalized.
    aliases: list[str] = field(default_factory=list)


@dataclass
class Evidence:
    matches: list[SymptomMatch] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def used(self) -> bool:
        return bool(self.candidates)

    def drug_names(self) -> dict[str, str]:
        """Normalized name -> display name of every drug linked to a candidate."""
        return {normalize(d["name"]): d["name"] for c in self.candidates for d in c.drugs}


class KnowledgeIndex:
    """Search structures over the knowledge tables, built on first use and
    rebuilt when the data changes."""

    def __init__(self, engine: Engine, embedder: Embedder | None, cache_dir: Path):
        self._engine = engine
        self._embedder = embedder
        self._cache_dir = cache_dir
        self._lock = threading.Lock()
        self._signature: tuple | None = None
        self._by_key: dict[str, int] = {}
        self._by_fuzzy: dict[str, int] = {}
        self._names: dict[int, str] = {}
        self._symptom_diseases: dict[int, list[int]] = {}
        self._disease_size: dict[int, int] = {}
        self._vectors: np.ndarray | None = None
        self._vector_ids: list[int] = []
        self._drug_keys: set[str] = set()
        # Disease details, medicines and precautions, held in memory so the
        # search answers without the database (Supabase) when the internet
        # is gone. Loaded with the rest while online; nothing is written to
        # disk except the symptom vectors.
        self._diseases: dict[int, tuple[str, str, str]] = {}  # id -> name, description, causes
        self._disease_by_key: dict[str, int] = {}  # name or unambiguous other name -> id
        self._disease_aliases: dict[int, list[str]] = {}
        self._drugs: dict[int, list[dict]] = {}
        self._precautions: dict[int, list[str]] = {}

    # --- building -----------------------------------------------------------

    def available(self) -> bool:
        if self._symptom_diseases:
            return True
        try:
            if "disease_links" not in inspect(self._engine).get_table_names():
                return False
            with Session(self._engine) as db:
                return db.scalar(select(DiseaseLink.id).limit(1)) is not None
        except Exception:
            return False  # database unreachable and nothing loaded yet

    def warm(self) -> None:
        """Builds the index ahead of the first request. Never raises."""
        try:
            self._ensure()
        except Exception:
            log.exception("Could not build the knowledge index")

    def _ensure(self) -> bool:
        """Loads or refreshes the index. False when there is no knowledge.
        Without the database (offline), a loaded index keeps serving."""
        try:
            return self._refresh()
        except Exception as e:
            if self._symptom_diseases:
                log.info("Knowledge database unreachable, using the loaded index: %s", str(e)[:120])
                return True
            raise

    def _refresh(self) -> bool:
        if "disease_links" not in inspect(self._engine).get_table_names():
            return False
        with self._lock, Session(self._engine) as db:
            from sqlalchemy import func

            signature = (
                db.scalar(select(func.count()).select_from(DiseaseLink)),
                db.scalar(select(func.max(DiseaseLink.id))),
                db.scalar(select(func.count()).select_from(Symptom)),
            )
            if signature == self._signature:
                return bool(self._symptom_diseases)
            self._build(db)
            self._signature = signature
            return bool(self._symptom_diseases)

    def _build(self, db: Session) -> None:
        sizes: dict[int, int] = {}
        pairs = db.execute(
            select(DiseaseLink.disease_id, DiseaseLink.symptom_id).where(
                DiseaseLink.symptom_id.is_not(None)
            )
        ).all()
        for disease_id, _ in pairs:
            sizes[disease_id] = sizes.get(disease_id, 0) + 1
        self._disease_size = {d: n for d, n in sizes.items() if n <= MAX_SYMPTOMS_PER_DISEASE}
        symptom_diseases: dict[int, list[int]] = {}
        for disease_id, symptom_id in pairs:
            if disease_id in self._disease_size:
                symptom_diseases.setdefault(symptom_id, []).append(disease_id)
        self._symptom_diseases = symptom_diseases

        # Only symptoms that lead to a disease are worth matching.
        self._by_key, self._by_fuzzy, self._names = {}, {}, {}
        texts: list[str] = []
        ids: list[int] = []
        rows = db.execute(select(Symptom.id, Symptom.name, Symptom.normalized_name, Symptom.aliases))
        for symptom_id, name, key, aliases in rows:
            if symptom_id not in symptom_diseases:
                continue
            self._names[symptom_id] = name
            self._by_key[key] = symptom_id
            self._by_fuzzy.setdefault(fuzzy_key(key), symptom_id)
            texts.append(name)
            ids.append(symptom_id)
            for alias in aliases or []:
                alias_key = normalize(alias)
                self._by_key.setdefault(alias_key, symptom_id)
                self._by_fuzzy.setdefault(fuzzy_key(alias_key), symptom_id)
                texts.append(alias)
                ids.append(symptom_id)
        self._vector_ids = ids
        self._vectors = self._embed_cached(texts)
        # Names of five letters or more: shorter ones ("iron", "zinc") are
        # also everyday words.
        self._drug_keys = {
            key
            for key in db.scalars(select(Drug.normalized_name))
            if len(key) >= 5 and key not in _EVERYDAY_SUBSTANCES
        }
        self._diseases, self._disease_by_key, self._disease_aliases = {}, {}, {}
        alias_owners: dict[str, set[int]] = {}
        for disease_id, name, key, description, causes, aliases in db.execute(
            select(Disease.id, Disease.name, Disease.normalized_name, Disease.description, Disease.causes,
                   Disease.aliases)
        ):
            self._diseases[disease_id] = (name, description or "", causes or "")
            self._disease_by_key[key] = disease_id
            for alias in aliases or []:
                akey = normalize(str(alias))
                if len(akey) >= 4 and akey != key:
                    alias_owners.setdefault(akey, set()).add(disease_id)
        # Another name finds its disease ("scabies" -> Acariasis), unless two
        # diseases share it or it is some disease's own name.
        for akey, owners in alias_owners.items():
            if len(owners) == 1 and akey not in self._disease_by_key:
                (owner,) = owners
                self._disease_by_key[akey] = owner
                self._disease_aliases.setdefault(owner, []).append(akey)
        self._drugs = {}
        for disease_id, name, uses in db.execute(
            select(DiseaseLink.disease_id, Drug.name, Drug.uses)
            .join(Drug, DiseaseLink.drug_id == Drug.id)
            .order_by(DiseaseLink.disease_id, Drug.name)
        ):
            found = self._drugs.setdefault(disease_id, [])
            if len(found) < 12:
                found.append({"name": name, "uses": (uses or "")[:240]})
        self._precautions = {}
        for disease_id, line in db.execute(
            select(Precaution.disease_id, Precaution.precaution).order_by(Precaution.id)
        ):
            found = self._precautions.setdefault(disease_id, [])
            if len(found) < 8:
                found.append(line)
        log.info(
            "Knowledge index: %d symptoms, %d diseases, vectors %s",
            len(self._names), len(self._disease_size), "on" if self._vectors is not None else "off",
        )  # fmt: skip

    def _embed_cached(self, texts: list[str]) -> np.ndarray | None:
        """Symptom vectors, computed once per data version and kept on disk."""
        if self._embedder is None or not texts:
            return None
        digest = hashlib.sha256(
            (self._embedder.model + "\n" + "\n".join(texts)).encode()
        ).hexdigest()[:24]
        path = self._cache_dir / f"symptoms-{digest}.npy"
        if path.exists():
            return np.load(path)
        try:
            vectors = self._embedder.embed(texts)
        except (httpx.HTTPError, KeyError) as e:
            log.warning("Symptom embeddings unavailable, matching by name only: %s", e)
            return None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        np.save(path, vectors)
        return vectors

    # --- searching ----------------------------------------------------------

    def match_symptoms(
        self, groups: list[list[str]]
    ) -> tuple[list[SymptomMatch], list[str]]:
        """Matches each of the patient's symptoms, given as a group of
        wordings for it (clinical term, their own words). Returns the matches
        and the symptoms nothing was found for."""
        matches: dict[int, SymptomMatch] = {}
        pending: list[tuple[int, str]] = []
        for group, phrases in enumerate(groups):
            for phrase in dict.fromkeys(p.strip() for p in phrases if p and p.strip()):
                key = normalize(phrase)
                symptom_id = self._by_key.get(key, self._by_fuzzy.get(fuzzy_key(key)))
                if symptom_id is not None:
                    matches.setdefault(
                        symptom_id,
                        SymptomMatch(phrase, symptom_id, self._names[symptom_id], 1.0, "name", group),
                    )
                # Even a named symptom is searched by meaning, to pick up the
                # other names the knowledge base files it under.
                pending.append((group, phrase))

        if pending and self._vectors is not None:
            try:
                queries = self._embedder.embed([phrase for _, phrase in pending])
            except (httpx.HTTPError, KeyError):
                queries = None
            if queries is not None:
                similarity = queries @ self._vectors.T
                for (group, phrase), row in zip(pending, similarity):
                    order = np.argsort(row)[::-1][: MAX_NEIGHBOURS * 4]
                    taken = 0
                    for position, index in enumerate(order):
                        score = float(row[index])
                        # The best neighbour needs MIN_SIMILARITY; further
                        # ones must be near-synonyms.
                        if score < (MIN_SIMILARITY if position == 0 else SYNONYM_SIMILARITY):
                            break
                        symptom_id = self._vector_ids[index]
                        if symptom_id not in matches:
                            matches[symptom_id] = SymptomMatch(
                                phrase, symptom_id, self._names[symptom_id], score, "meaning", group
                            )
                            taken += 1
                        if taken >= MAX_NEIGHBOURS:
                            break

        found = {m.group for m in matches.values()}
        unmatched = [phrases[0] for group, phrases in enumerate(groups) if group not in found and phrases]
        return list(matches.values()), unmatched

    def find_in_text(self, text: str) -> list[str]:
        """Symptom names that literally occur in free text, longest first.
        A safety net for when the language model's phrase list misses one."""
        words = normalize(text).split()
        found: list[str] = []
        i = 0
        while i < len(words):
            for size in range(min(5, len(words) - i), 0, -1):
                key = " ".join(words[i : i + size])
                # Single short words ("pain", "back") are too ambiguous alone.
                if (size > 1 or len(key) > 5) and key in self._by_key:
                    found.append(self._names[self._by_key[key]])
                    i += size - 1
                    break
            i += 1
        return found

    def retrieve(self, groups: list[list[str]], free_text: str = "") -> Evidence:
        """Evidence for a patient. `groups` holds one list of wordings per
        symptom; `free_text` is the raw description they came from."""
        if not self._ensure():
            return Evidence(unmatched=[g[0] for g in groups if g])
        groups = [list(g) for g in groups if g]
        matches, unmatched = self.match_symptoms(groups)
        # Symptom names that occur literally in the text but were not picked
        # up above each become a symptom of their own.
        known = {m.symptom_id for m in matches}
        for name in self.find_in_text(free_text):
            symptom_id = self._by_key[normalize(name)]
            if symptom_id not in known:
                known.add(symptom_id)
                matches.append(SymptomMatch(name, symptom_id, name, 1.0, "name", len(groups)))
                groups.append([name])
        if not matches:
            return Evidence(unmatched=unmatched)

        total_diseases = len(self._disease_size)
        weight: dict[int, float] = {}
        for m in matches:
            frequency = len(self._symptom_diseases[m.symptom_id])
            # Rare symptoms say more about which disease it is than common ones.
            weight[m.symptom_id] = math.log(1 + total_diseases / frequency) * m.score
        group_of = {m.symptom_id: m.group for m in matches}
        # One complaint counts once, however many rows matched it.
        group_weight: dict[int, float] = {}
        for symptom_id, w in weight.items():
            group = group_of[symptom_id]
            group_weight[group] = max(group_weight.get(group, 0.0), w)
        presentation = sum(group_weight.values())

        explained: dict[int, list[int]] = {}
        for m in matches:
            for disease_id in self._symptom_diseases[m.symptom_id]:
                explained.setdefault(disease_id, []).append(m.symptom_id)

        scored: list[tuple[float, int]] = []
        for disease_id, symptom_ids in explained.items():
            best: dict[int, float] = {}
            for symptom_id in symptom_ids:
                group = group_of[symptom_id]
                best[group] = max(best.get(group, 0.0), weight[symptom_id])
            # With several symptoms reported, one shared symptom is no evidence.
            if len(group_weight) >= 3 and len(best) < 2:
                continue
            coverage = sum(best.values()) / presentation
            # Of two diseases explaining the same symptoms, prefer the one for
            # which those symptoms are a larger part of its picture.
            focus = len(best) / math.sqrt(self._disease_size[disease_id])
            scored.append((coverage * (0.6 + 0.4 * min(1.0, focus)), disease_id))
        scored.sort(reverse=True)
        top = scored[:MAX_CANDIDATES]

        names = {m.symptom_id: m.name for m in matches}
        candidates = [
            self._candidate(disease_id, score, [names[s] for s in explained[disease_id]])
            for score, disease_id in top
        ]
        return Evidence(matches=matches, unmatched=unmatched, candidates=candidates)

    def disease_names(self) -> list[str]:
        """Every disease name held in memory (for the doctor's type-ahead)."""
        return [name for name, _, _ in self._diseases.values() if name]

    def mentions_drug(self, text: str) -> bool:
        """True when the text names a medicine from the knowledge base."""
        words = normalize(text).split()
        return any(
            " ".join(words[i : i + size]) in self._drug_keys
            for size in (1, 2, 3)
            for i in range(len(words) - size + 1)
        )

    def lookup(self, condition: str) -> Candidate | None:
        """The knowledge-base disease a condition name refers to, when the
        search did not surface it: same name or alias, or a disease whose
        name is contained in the condition ("acute bacterial cystitis")."""
        if not self._ensure():
            return None
        key = normalize(condition)
        disease_id = self._disease_by_key.get(key)
        if disease_id is None:
            words = key.split()
            # Longest contained name first; one-word names are too loose.
            for span in sorted(
                {" ".join(words[i:j]) for i in range(len(words)) for j in range(i + 2, len(words) + 1)},
                key=len,
                reverse=True,
            ):
                found = self._disease_by_key.get(span)
                if found is not None and (found in self._disease_size or self._diseases[found][1]):
                    disease_id = found
                    break
        if disease_id is None:
            return None
        self._disease_size.setdefault(disease_id, 0)
        return self._candidate(disease_id, 0.0, [])

    def _candidate(self, disease_id: int, score: float, matched: list[str]) -> Candidate:
        name, description, causes = self._diseases[disease_id]
        return Candidate(
            disease_id=disease_id,
            name=name,
            score=round(score, 3),
            matched=sorted(matched),
            symptom_count=self._disease_size[disease_id],
            description=description,
            causes=causes,
            drugs=list(self._drugs.get(disease_id, [])),
            precautions=list(self._precautions.get(disease_id, [])),
            aliases=list(self._disease_aliases.get(disease_id, [])),
        )
