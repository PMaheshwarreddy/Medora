"""Community datasets from Hugging Face, one small mapping per dataset (code,
no model). They land in their own rows, tier 5, testing only:

- disease -> symptom lists: kb_disease_symptoms (and passages where there is text)
- medicine brands: kb_drug_products (composition parsed into drug + strength)
- a list of disease names: condition terms

The same data uploaded under several names is loaded once: brand sets skip
brands another source already holds, and disease lists drop repeated pairs.
"""

import csv
import json
import re
from pathlib import Path

import pyarrow.parquet as pq

from ..drugnames import canonical, stripped
from ..load import Bundle
from ..sources import Source
from ..text import clean, normalize

csv.field_size_limit(10**9)

_PART = re.compile(r"^\s*(?P<name>[^()]+?)\s*(?:\((?P<strength>[^)]*)\))?\s*$")
_FORMS = ("tablet", "capsule", "syrup", "suspension", "injection", "infusion", "drop", "drops", "cream", "ointment", "gel",
          "lotion", "inhaler", "respules", "spray", "solution", "powder", "sachet", "suppository", "patch", "soap", "shampoo")


def _rows(path: Path):
    if path.suffix == ".parquet":
        yield from pq.read_table(path).to_pylist()
    elif path.suffix == ".csv":
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            yield from csv.DictReader(f)
    else:
        text = path.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
            yield from (data if isinstance(data, list) else data.get("data") or [data])
        except ValueError:
            for line in text.splitlines():
                if line.strip():
                    yield json.loads(line)


def _symptoms(value) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[,|;\n]", str(value or ""))
    out, seen = [], set()
    for s in items:
        s = clean(str(s).replace("_", " ")).strip(" .-•")
        n = normalize(s)
        if n and n not in seen and len(n) <= 120:
            seen.add(n)
            out.append(s)
    return out


def _disease_symptoms(bundle: Bundle, disease: str, symptoms: list[str], seen: set) -> None:
    disease = clean(str(disease or "")).strip()
    dn = normalize(disease)
    if not dn:
        return
    for s in symptoms:
        sn = normalize(s)
        if (dn, sn) in seen:
            bundle.stats["repeated pairs skipped"] += 1
            continue
        seen.add((dn, sn))
        bundle.add("kb_disease_symptoms", disease=disease, normalized=dn, symptom=s, symptom_normalized=sn)


def composition(text: str) -> list[dict]:
    text = clean(str(text or "")).replace("\n", " ")
    if not text or text in ("-", "NA"):
        return []
    parts = re.split(r"\s\+\s|\+", text) if "+" in text else re.split(r",\s*(?![^()]*\))", text)
    out = []
    for p in parts:
        p = p.strip()
        # the strength is the last bracket with a number in it: "Progesterone (Natural Micronized) (300mg)"
        m = re.match(r"^(?P<name>.*?)\s*\((?P<strength>[^()]*\d[^()]*|NA)\)\s*$", p)
        name, strength = (m.group("name"), m.group("strength")) if m else (p, "")
        name = name.strip().strip(".")
        if name and re.search(r"[A-Za-z]{3}", name):
            out.append({"drug": name, "strength": "" if strength == "NA" else strength.strip()})
    return out


def composition_key(parts: list[dict]) -> str:
    joined = " ".join(p["drug"] for p in parts)
    return stripped(joined) or canonical(joined)


def _form(brand: str) -> str:
    for w in reversed(normalize(brand).split()):
        if w in _FORMS:
            return w
    return ""


def _price(value) -> float | None:
    try:
        return round(float(str(value).replace(",", "")), 2)
    except ValueError:
        return None


def _product(bundle: Bundle, brand: str, comp: str, seen: set, **extra) -> None:
    brand = clean(str(brand or ""))
    n = normalize(brand)
    if not n:
        return
    if n in seen:
        bundle.stats["brands already held"] += 1
        return
    parts = composition(comp)
    if not parts:
        bundle.refuse({"brand": brand, "composition": comp}, "no composition")
        return
    seen.add(n)
    subs = extra.pop("substitutes", "") or ""
    bundle.add(
        "kb_drug_products", brand=brand, normalized=n, composition=parts, form=_form(brand),
        manufacturer=clean(str(extra.get("manufacturer") or "")), uses=clean(str(extra.get("uses") or "")),
        side_effects=clean(str(extra.get("side_effects") or "")), pack=clean(str(extra.get("pack") or "")),
        price_inr=_price(extra.get("price")), composition_key=composition_key(parts),
        substitutes=[s.strip() for s in str(subs).split(",") if s.strip()][:20],
    )


def _held_brands(conn, source: Source) -> set:
    return {n for (n,) in conn.execute(
        "select p.normalized from kb_drug_products p join kb_sources s on s.id = p.source_id where s.key <> %s", (source.key,)
    )}


# --- one mapping per dataset ------------------------------------------------

def _disease_database(paths, bundle, **_):
    seen = set()
    for r in _rows(paths[0]):
        disease = clean(r.get("disease", ""))
        _disease_symptoms(bundle, disease, _symptoms(r.get("common_symptom")), seen)
        body = "\n".join(x for x in (f"Common symptoms: {clean(r.get('common_symptom', ''))}",
                                     f"Treatment: {clean(r.get('treatment', ''))}") if not x.endswith(": "))
        if disease and body:
            bundle.passages(breadcrumb=f"Disease Database (Hugging Face) › {disease}", body=body,
                            section="community_disease", topic=disease)


def _mayo(paths, bundle, **_):
    done = set()
    sections = ("Overview", "Symptoms", "When to See Doctor", "Causes", "Risk Factor", "Complications", "Preventions")
    for r in _rows(paths[0]):
        disease = clean(r.get("Disease", ""))
        if not disease or normalize(disease) in done:
            continue
        done.add(normalize(disease))
        for sec in sections:
            body = clean(r.get(sec) or "")
            if body and body.lower() not in ("nan", "none"):
                bundle.passages(breadcrumb=f"Disease guide (Hugging Face) › {disease} › {sec}", body=body,
                                section=f"community_{normalize(sec).replace(' ', '_')}", topic=disease)
    bundle.stats["diseases"] = len(done)


def _medlineplus_symptoms(paths, bundle, **_):
    seen = set()
    for r in _rows(paths[0]):
        _disease_symptoms(bundle, r.get("Disease_Name"), _symptoms(str(r.get("Symptom_List") or "").replace("|", "\n")), seen)


def _kaggle_41(paths, bundle, **_):
    seen = set()
    for r in _rows(paths[0]):
        disease = r.get("Disease") or r.get("disease")
        values = r.get("symptoms") or [v for k, v in r.items() if k.lower().startswith("symptom") and v]
        _disease_symptoms(bundle, disease, _symptoms(values), seen)


def _json_symptom(paths, bundle, conn, **_):
    """Part Kaggle set, part reversed co-occurrence pairs ('disease: Muscle
    Weakness, symptom: Angiolipoma'): a 'disease' that is only known as a
    symptom is refused."""
    symptom_names = {n for (n,) in conn.execute("select distinct normalized from kb_terms where kind = 'symptom'")}
    condition_names = {n for (n,) in conn.execute("select distinct normalized from kb_terms where kind = 'condition'")}
    seen, refused = set(), 0
    for r in _rows(paths[0]):
        disease = r.get("disease")
        dn = normalize(str(disease or ""))
        if dn in symptom_names and dn not in condition_names:
            refused += 1
            if refused <= 50:
                bundle.refuse(r, "the 'disease' is a symptom: a reversed or co-occurrence pair")
            continue
        _disease_symptoms(bundle, disease, _symptoms(r.get("symptoms")), seen)
    bundle.stats["reversed rows refused (50 kept as examples)"] = refused


def _columbia(paths, bundle, **_):
    seen = set()
    for r in _rows(paths[0]):
        _disease_symptoms(bundle, r.get("disease"), _symptoms(list(r.get("symptoms") or [])), seen)


def _symptoms_doctors(paths, bundle, **_):
    seen = set()
    for r in _rows(paths[0]):
        disease = clean(r.get("disease", ""))
        _disease_symptoms(bundle, disease, _symptoms(r.get("symptoms")), seen)
        body = "\n".join(f"{k.capitalize()}: {clean(str(r.get(k) or ''))}" for k in ("symptoms", "cures", "doctor", "risk level") if r.get(k))
        if disease:
            bundle.passages(breadcrumb=f"Symptoms and doctors (Hugging Face) › {disease}", body=body,
                            section="community_disease", topic=disease)


def _all_diseases(paths, bundle, **_):
    seen = set()
    for r in _rows(paths[0]):
        names = [clean(x) for x in str(r.get("name_english") or "").split("|") if clean(x)]
        if not names:
            continue
        concept = f"NAME:{normalize(names[-1])}"
        for i, name in enumerate(names):
            n = normalize(name)
            if n and (concept, n) not in seen:
                seen.add((concept, n))
                bundle.add("kb_terms", kind="condition", concept=concept, term=name, normalized=n, preferred=i == len(names) - 1, umls="")


def _indian_brands(paths, bundle, conn, source, **_):
    seen = _held_brands(conn, source)
    for r in _rows(paths[0]):
        _product(bundle, r.get("Medicine_Name"), r.get("Active_Ingredients"), seen, manufacturer=r.get("Manufacturer"),
                 uses=r.get("Primary_Use_Cases"), side_effects=r.get("Side_Effects"), pack=r.get("Pack_Size"),
                 price=r.get("Price_INR"), substitutes=r.get("Substitutes_Available"))


def _1mg(paths, bundle, conn, source, **_):
    seen = _held_brands(conn, source)
    for r in _rows(paths[0]):
        _product(bundle, r.get("name"), r.get("composition"), seen, uses=r.get("uses"), side_effects=r.get("side_effects"))


_QA = re.compile(r"Medicine Name:\s*(?P<name>.*?),\s*Composition:\s*(?P<comp>.*?),\s*Uses:\s*(?P<uses>.*?),\s*Side Effects:\s*(?P<se>.*)$", re.S)


def _1mg_qa(paths, bundle, conn, source, **_):
    seen = _held_brands(conn, source)
    for path in paths:
        for r in _rows(path):
            m = _QA.match(str(r.get("context") or ""))
            if not m:
                bundle.refuse({"context": str(r.get("context"))[:200]}, "unrecognised record")
                continue
            _product(bundle, m["name"], m["comp"], seen, uses=m["uses"], side_effects=m["se"])


_INSTRUCT = re.compile(r"Medicine Name:\s*(?P<name>.*?)\.\s*Composition:\s*(?P<comp>.*?)\.\s*Side Effects:\s*(?P<se>.*?)\.?$", re.S)


def _1mg_instruct(paths, bundle, conn, source, **_):
    seen = _held_brands(conn, source)
    for r in _rows(paths[0]):
        m = _INSTRUCT.match(str(r.get("output1") or ""))
        if not m:
            bundle.refuse({"output1": str(r.get("output1"))[:200]}, "unrecognised record")
            continue
        uses = re.sub(r"^Uses:\s*", "", str(r.get("input") or "")).rstrip(".")
        _product(bundle, m["name"], m["comp"], seen, uses=uses, side_effects=m["se"])


READERS = {
    "hf-disease-database": _disease_database, "hf-mayo-diseases": _mayo, "hf-medlineplus-symptoms": _medlineplus_symptoms,
    "hf-kaggle-41": _kaggle_41, "hf-json-symptom": _json_symptom, "hf-columbia-134": _columbia,
    "hf-symptoms-doctors": _symptoms_doctors, "hf-all-diseases": _all_diseases, "hf-indian-brands": _indian_brands,
    "hf-1mg-medicines": _1mg, "hf-1mg-medicines-qa": _1mg_qa, "hf-1mg-medicines-instruct": _1mg_instruct,
}


def read(source: Source, paths: list[Path], conn=None, **_) -> Bundle:
    bundle = Bundle()
    READERS[source.key](paths, bundle, conn=conn, source=source)
    return bundle
