"""WHO Model List of Essential Medicines (24th list, 2025).

Medicine names sit in the left column, vertically centred beside their
dosage forms. Pairing each name with its strength lines by position was
tried (2026-10-27) and put strengths on the wrong medicine at block
boundaries (diazepam got carbamazepine's tablets), so it is not done: a wrong
strength is worse than none. What is taken: each medicine and its sections
(kb_drugs.who_eml), and each section as passages, where the strengths and
the antibiotic first/second-choice lists are kept as printed, columns apart
by " | ".
"""

import re
from pathlib import Path

import pdfplumber

from ..drugnames import canonical
from ..load import Bundle
from ..sources import Source
from ..text import clean, normalize
from .nfi import lines_of

_SECTION = re.compile(r"^(\d{1,2}(\.\d+)*)\.?\s+([A-Z].{3,})$")
_MARKS = re.compile(r"\s*(\[c\]|\*|\b[a-d]\b)+\s*$")
_STOP = {"according", "at", "be", "through", "excluding", "level", "in", "of", "for", "to", "the", "with", "and", "is",
         "are", "not", "national", "guidelines", "supplied", "free", "charge", "agents", "derivatives", "antagonists"}
_NOT_NAME = re.compile(r"^(therapeutic alternatives|complementary list|first choice|second choice|note|-|−|•|\d)", re.I)


def read(source: Source, paths: list[Path], **_) -> Bundle:
    bundle = Bundle()
    section, sections = "", {}
    started = False
    with pdfplumber.open(paths[0]) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            lines = lines_of(page)
            if not lines:
                continue
            text0 = " ".join(s for _, s in lines[0][1])
            if text0.startswith("WHO Model List of Essential Medicines"):
                lines = lines[1:]
            elif not started:
                continue
            left = min((x for x, _ in lines), default=0)
            for x, segs in lines:
                first = segs[0][1].strip()
                m = _SECTION.match(" ".join(s for _, s in segs).strip())
                if m and x < left + 15 and len(segs) == 1:
                    started = True
                    section = f"{m.group(1)} {m.group(3).strip().capitalize() if m.group(3).isupper() else m.group(3).strip()}"
                    sections.setdefault(section, [])
                    continue
                if not started or not section:
                    continue
                if first.lower().startswith("index") and x < left + 15:
                    started = False
                    break
                sections[section].append(" | ".join(s for _, s in segs))
                name = _MARKS.sub("", first).strip()
                if (x < left + 40 and first[:1].islower() and len(name) < 60 and not _NOT_NAME.match(name)
                        and segs[0][0] < 200 and not (set(re.findall(r"[a-z]+", name.lower())) & _STOP)
                        and normalize(name) != "acetate"):
                    entry = bundle.drugs.get(canonical(name))
                    secs = (entry or {}).get("who_eml", {}).get("sections", [])
                    if section not in secs:
                        bundle.drug(name, who_eml={"sections": secs + [section], "page": number})
    for sec, lines in sections.items():
        body = clean("\n".join(lines))
        if body:
            bundle.passages(breadcrumb=f"WHO Essential Medicines 2025 › {sec}", body=body, section="essential_list", topic=sec)
    bundle.stats["medicines"] = len(bundle.drugs)
    return bundle
