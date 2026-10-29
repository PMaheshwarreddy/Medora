"""Disease Ontology (conditions), Human Phenotype Ontology and Symptom
Ontology (symptoms): names, exact synonyms and cross-references only."""

import re
from pathlib import Path

from lxml import etree

from ..load import Bundle
from ..sources import Source
from ..text import normalize

_SYN = re.compile(r'^synonym: "(.*)" (EXACT|RELATED|BROAD|NARROW)')
_HP_ROOT = "HP:0000118"  # Phenotypic abnormality: what a patient or doctor observes


def obo_terms(path: Path):
    term: dict | None = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("["):
                if term:
                    yield term
                term = {"syn": [], "xref": [], "is_a": []} if line == "[Term]" else None
                continue
            if term is None or ": " not in line:
                continue
            tag, value = line.split(": ", 1)
            if tag == "synonym":
                m = _SYN.match(line)
                if m and m.group(2) == "EXACT":
                    term["syn"].append(m.group(1).replace('\\"', '"'))
            elif tag == "xref":
                term["xref"].append(value.split(" ")[0])
            elif tag == "is_a":
                term["is_a"].append(value.split(" ")[0])
            elif tag == "def":
                term["def"] = value.split('" [')[0].strip('"')
            elif tag in ("id", "name", "is_obsolete"):
                term[tag] = value
    if term:
        yield term


def _xrefs(term: dict, *prefixes: str) -> list[str]:
    out = []
    for x in term["xref"]:
        for p in prefixes:
            if x.startswith(p + ":"):
                out.append(x.split(":", 1)[1])
    return sorted(set(out))


def _terms(bundle: Bundle, kind: str, concept: str, name: str, synonyms: list[str], umls: str = "") -> None:
    seen = set()
    for i, t in enumerate([name, *synonyms]):
        n = normalize(t)
        if not n or n in seen:
            continue
        seen.add(n)
        bundle.add("kb_terms", kind=kind, concept=concept, term=t, normalized=n, preferred=i == 0, umls=umls)


def _read_doid(path: Path, bundle: Bundle) -> None:
    for t in obo_terms(path):
        if t.get("is_obsolete") == "true" or not t.get("id", "").startswith("DOID:") or not t.get("name"):
            continue
        umls = _xrefs(t, "UMLS_CUI")
        bundle.add(
            "kb_conditions", doid=t["id"], name=t["name"], normalized=normalize(t["name"]), definition=t.get("def", ""),
            parents=t["is_a"], icd10cm=_xrefs(t, "ICD10CM"), icd11=_xrefs(t, "ICD11"), mesh=_xrefs(t, "MESH"), umls=umls,
        )
        _terms(bundle, "condition", t["id"], t["name"], t["syn"], umls[0] if umls else "")


def _read_hpo(path: Path, bundle: Bundle) -> None:
    terms = {t["id"]: t for t in obo_terms(path) if t.get("is_obsolete") != "true" and t.get("id", "").startswith("HP:")}
    children: dict[str, list[str]] = {}
    for tid, t in terms.items():
        for p in t["is_a"]:
            children.setdefault(p, []).append(tid)
    keep, stack = set(), [_HP_ROOT]
    while stack:
        tid = stack.pop()
        if tid not in keep:
            keep.add(tid)
            stack.extend(children.get(tid, []))
    keep.discard(_HP_ROOT)
    for tid in sorted(keep):
        t = terms[tid]
        umls = _xrefs(t, "UMLS", "UMLS_CUI")
        _terms(bundle, "symptom", tid, t["name"], t["syn"], umls[0] if umls else "")
    bundle.stats["outside phenotypic abnormality (skipped)"] = len(terms) - len(keep) - 1


_NS = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "oio": "http://www.geneontology.org/formats/oboInOwl#",
}


def _read_symp(path: Path, bundle: Bundle) -> None:
    tree = etree.parse(str(path))
    for cls in tree.iterfind("owl:Class", _NS):
        about = cls.get(f"{{{_NS['rdf']}}}about", "")
        label = cls.findtext("rdfs:label", namespaces=_NS)
        if "SYMP_" not in about or not label:
            continue
        if (cls.findtext("owl:deprecated", namespaces=_NS) or "").lower() == "true":
            continue
        syns = [s.text for s in cls.iterfind("oio:hasExactSynonym", _NS) if s.text]
        umls = [x.text.split(":", 1)[1] for x in cls.iterfind("oio:hasDbXref", _NS) if x.text and x.text.startswith("UMLS")]
        _terms(bundle, "symptom", "SYMP:" + about.rsplit("_", 1)[1], label, syns, umls[0] if umls else "")


def read(source: Source, paths: list[Path], **_) -> Bundle:
    bundle = Bundle()
    {"doid": _read_doid, "hpo": _read_hpo, "symp": _read_symp}[source.key](paths[0], bundle)
    return bundle
