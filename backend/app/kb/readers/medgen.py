"""MedGen names (MGCONSO.RRF): English synonyms for concepts that Disease
Ontology, HPO or the Symptom Ontology already link by UMLS CUI. Nothing new
is created from MedGen; it only adds other names for what is there."""

from pathlib import Path

from ..load import Bundle
from ..sources import Source
from ..text import normalize


def read(source: Source, paths: list[Path], conn, **_) -> Bundle:
    known = {cui: (kind, concept) for cui, kind, concept in conn.execute(
        "select distinct on (umls) umls, kind, concept from kb_terms where umls <> '' order by umls, preferred desc"
    )}
    have = {(c, n) for c, n in conn.execute("select concept, normalized from kb_terms")}
    bundle = Bundle()
    seen = set()
    with open(paths[0], encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.split("|")
            cui, sab, text, suppress = p[0], p[8], p[11], p[12]
            if cui not in known or suppress != "N":
                continue
            kind, concept = known[cui]
            n = normalize(text)
            if len(n) < 3 or (concept, n) in have or (cui, n) in seen or len(n) > 120:
                continue
            seen.add((cui, n))
            bundle.add("kb_terms", kind=kind, concept=f"UMLS:{cui}", term=text, normalized=n, preferred=False, umls=cui)
    bundle.stats["concepts matched"] = len({c for c, _ in seen})
    return bundle
