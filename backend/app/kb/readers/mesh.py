"""MeSH descriptors for diseases (C), mental disorders (F03) and signs and
symptoms (C23.888): the preferred concept's terms only (its narrower
concepts are different things)."""

from pathlib import Path

from lxml import etree

from ..load import Bundle
from ..sources import Source
from ..text import normalize


def read(source: Source, paths: list[Path], **_) -> Bundle:
    bundle = Bundle()
    for _, rec in etree.iterparse(str(paths[0]), tag="DescriptorRecord"):
        trees = [t.text for t in rec.iterfind("TreeNumberList/TreeNumber")]
        if any(t.startswith("C23.888") for t in trees):
            kind = "symptom"
        elif any(t.startswith("C") or t.startswith("F03") for t in trees):
            kind = "condition"
        else:
            rec.clear()
            continue
        ui = rec.findtext("DescriptorUI")
        name = rec.findtext("DescriptorName/String")
        concept = next((c for c in rec.iterfind("ConceptList/Concept") if c.get("PreferredConceptYN") == "Y"), None)
        names = [name] + ([t.findtext("String") for t in concept.iterfind("TermList/Term")] if concept is not None else [])
        seen = set()
        for i, t in enumerate(names):
            n = normalize(t or "")
            if n and n not in seen:
                seen.add(n)
                bundle.add("kb_terms", kind=kind, concept=f"MESH:{ui}", term=t, normalized=n, preferred=i == 0, umls="")
        rec.clear()
        while rec.getprevious() is not None:
            del rec.getparent()[0]
    return bundle
