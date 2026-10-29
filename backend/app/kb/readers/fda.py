"""US FDA drug labels (openFDA, 14 files, 8 GB): one label per medicine and route.

Only medicines already in the knowledge base (NLEM, NFI, WHO) are kept: the
labels are a fallback for safety detail, not a catalogue. US names meet the
Indian ones through `drugnames` (acetaminophen = paracetamol). For each
medicine and route the most complete label wins (prescription first, then
the most sections, then the newest). Its safety sections become
kb_drug_safety rows and passages; its dosing becomes a passage marked as a
US label (Indian sources come first for doses).
"""

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import ijson

from ..drugnames import canonical, stripped
from ..load import Bundle
from ..sources import Source
from ..text import clean

SECTIONS = (  # label field, safety kind ('' = passage only), heading
    ("boxed_warning", "warning", "Boxed warning"),
    ("indications_and_usage", "", "Indications"),
    ("dosage_and_administration", "", "Dosage and administration"),
    ("contraindications", "contraindication", "Contraindications"),
    ("do_not_use", "contraindication", "Do not use"),
    ("warnings_and_cautions", "warning", "Warnings and precautions"),
    ("warnings", "warning", "Warnings"),
    ("ask_doctor", "precaution", "Ask a doctor before use"),
    ("stop_use", "warning", "Stop use"),
    ("drug_interactions", "interaction", "Drug interactions"),
    ("pregnancy", "pregnancy", "Pregnancy"),
    ("pregnancy_or_breast_feeding", "pregnancy", "Pregnancy or breast-feeding"),
    ("pediatric_use", "children", "Use in children"),
    ("overdosage", "overdose", "Overdose"),
)
MAX_WORDS = 1200  # per section; US warnings run to pages


def match_key(name: str) -> str:
    """Name for matching US labels: salt words dropped, unless the name is only
    salts ('Magnesium sulfate', 'Potassium nitrate'), then kept whole."""
    key = " ".join(w for w in stripped(name).split() if w != "acid")
    return key or " ".join(w for w in canonical(name).split() if w != "acid")


def _scan(args) -> dict:
    path, wanted = args
    best: dict[str, tuple] = {}
    with open(path, "rb") as f:
        for r in ijson.items(f, "results.item"):
            fda = r.get("openfda") or {}
            kinds = fda.get("product_type") or []
            if not fda.get("generic_name") or not ({"HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG"} & set(kinds)):
                continue
            key = match_key(fda["generic_name"][0])
            if key not in wanted:
                continue
            route = ((fda.get("route") or ["unspecified"])[0]).lower()
            fields = {name: " ".join(r[name]) for name, _, _ in SECTIONS if r.get(name)}
            score = ("HUMAN PRESCRIPTION DRUG" in kinds, len(fields), r.get("effective_time", ""))
            slot = f"{key}|{route}"
            if slot not in best or score > best[slot][0]:
                best[slot] = (score, {"key": key, "route": route, "generic": fda["generic_name"][0],
                                      "set_id": r.get("set_id", ""), "effective": r.get("effective_time", ""),
                                      "fields": fields})
    return {k: v[1] for k, v in best.items()}


def _cap(text: str) -> str:
    ws = clean(text).split(" ")
    return " ".join(ws) if len(ws) <= MAX_WORDS else " ".join(ws[:MAX_WORDS]) + " … (shortened; see the full US label)"


def read(source: Source, paths: list[Path], conn, **_) -> Bundle:
    wanted: dict[str, str] = {}
    for name, in conn.execute("select name from kb_drugs where sources && array['nfi-2011','nlem-2022','who-eml-2025']"):
        wanted.setdefault(match_key(name), name)
    for term, concept in conn.execute("select term, concept from kb_terms where kind = 'drug'"):
        k = match_key(term)
        if k and k not in wanted:
            name = conn.execute("select name from kb_drugs where 'DRUG:' || normalized = %s", (concept,)).fetchone()
            if name:
                wanted[k] = name[0]
    wanted.pop("", None)
    keys = set(wanted)
    with ProcessPoolExecutor(max_workers=min(len(paths), 6)) as pool:
        results = list(pool.map(_scan, [(p, keys) for p in paths]))
    labels: dict[str, dict] = {}
    for part in results:
        for slot, label in part.items():
            old = labels.get(slot)
            if old is None or (len(label["fields"]), label["effective"]) > (len(old["fields"]), old["effective"]):
                labels[slot] = label

    bundle = Bundle()
    for label in sorted(labels.values(), key=lambda x: (x["key"], x["route"])):
        name = wanted[label["key"]]
        key = bundle.drug(name)  # marks the medicine as having a US label
        bundle.drug_terms(label["generic"].title(), key)  # the US name as another spelling
        route = label["route"]
        crumb = f"FDA label (US) › {name} [{route}]"
        for field, kind, heading in SECTIONS:
            text = label["fields"].get(field)
            if not text:
                continue
            body = _cap(text)
            if kind:
                bundle.add("kb_drug_safety", page=None, drug=name, kind=kind, body=body)
            bundle.passages(breadcrumb=f"{crumb} › {heading}", body=body, section=f"drug:label_{kind or field}", topic=name)
        bundle.stats["labels"] += 1
    bundle.stats["medicines with a US label"] = len({lb["key"] for lb in labels.values()})
    bundle.stats["medicines without one"] = len(keys) - bundle.stats["medicines with a US label"]
    return bundle
