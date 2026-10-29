"""National List of Essential Medicines 2022: the medicine tables.

Each medicine: its NLEM code, section, care levels (P primary, S secondary,
T tertiary) and dosage forms with strengths. Read from the PDF's own tables
(pdfplumber), no model. The list ends where the alphabetical index begins;
the 'added' and 'deleted' annexes repeat it and are not read.
"""

import re
from pathlib import Path

import pdfplumber

from ..load import Bundle
from ..sources import Source
from ..text import clean, normalize

_CODE = re.compile(r"^\d+(\.\d+)+$")
_SECTION = re.compile(r"^(Section\s+\d+|\d+(\.\d+)*\s*-|\d+(\.\d+)+\s+[A-Z][a-z])", re.I)
_LEVELS = re.compile(r"^[PST](,\s*[PST])*$")
_MARKERS = re.compile(r"\s*\([A-E]\)")


def _key(form: str) -> str:
    return normalize(form).replace(" ", "")


def _name(raw: str) -> str:
    name = clean(raw).replace("\n", " ")
    name = name.replace("*", "").strip()
    return _MARKERS.sub("", name).strip()


def _forms(raw: str) -> list[str]:
    out: list[str] = []
    for line in clean(raw).split("\n"):
        if out and (line[:1] in "(+" or line[:1].islower() or out[-1].endswith(("-", "+"))):
            out[-1] = f"{out[-1]} {line}".replace("- ", "- ").strip()
        else:
            out.append(line)
    return out


def read(source: Source, paths: list[Path], **_) -> Bundle:
    bundle = Bundle()
    medicines: list[dict] = []
    notes: dict[str, list[str]] = {}
    section = ""
    with pdfplumber.open(paths[0]) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.lstrip().startswith("Alphabetical List"):
                break
            if number < 4:
                continue
            for table in page.extract_tables():
                width = max(len(r) for r in table)
                table = [list(r) + [None] * (width - len(r)) for r in table]
                # a column empty all the way down is a drawing artefact
                keep = [i for i in range(width) if any((r[i] or "").strip() for r in table if width < 3 or (r[1] or r[2] or "").strip())]
                for row in table:
                    cells = [(row[i] or "").strip() for i in keep]
                    while cells and not cells[-1]:
                        cells.pop()
                    if len(cells) == 5 and not cells[3]:
                        cells = cells[:3] + cells[4:]
                    if len(cells) == 1 and _SECTION.match(cells[0]):
                        section = clean(cells[0]).replace("\n", " ")
                        continue
                    if len(cells) == 1 and cells[0].startswith("*"):
                        continue  # footnote
                    filled = [c for c in cells if c]
                    if len(filled) == 4 and _CODE.match(filled[0]) and len(cells) > 4:
                        cells = filled
                    if len(cells) == 1 and len(cells[0]) > 60:
                        notes.setdefault(section, []).append(clean(cells[0]).replace("\n", " "))
                        continue
                    if len(cells) == 1 and _key(cells[0]) in {
                        _key(f) for m in medicines if m["page"] == number for r in m["rows"] for f in r["forms"]
                    }:
                        bundle.stats["form cells read twice"] += 1
                        continue
                    cells += [""] * (4 - len(cells)) if 2 <= len(cells) < 4 else []
                    if len(cells) != 4:
                        if any(cells):
                            bundle.refuse({"row": cells}, "unexpected table shape", number)
                        continue
                    code, name, levels, forms = cells
                    if code and not name and not levels and _SECTION.match(code):
                        section = clean(code).replace("\n", " ")
                        continue
                    if name == "Medicine" or (not name and not levels and not forms):
                        continue
                    if not _CODE.match(code) and not (not code and (name or levels)):
                        continue  # footnotes
                    if name and not levels and not forms:
                        bundle.refuse({"row": cells}, "medicine without level or form", number)
                        continue
                    levels = levels.replace(" ", "")
                    if levels and not _LEVELS.match(levels):
                        bundle.refuse({"row": cells}, f"unknown care level {levels!r}", number)
                        continue
                    entry = {"levels": levels.split(","), "forms": _forms(forms)}
                    if name:
                        medicines.append({"code": code or (medicines[-1]["code"] if medicines else ""), "name": _name(name),
                                          "section": section, "page": number, "rows": [entry]})
                    elif medicines:
                        medicines[-1]["rows"].append(entry)
    by_section: dict[str, list[str]] = {}
    merged: dict[str, dict] = {}
    for m in medicines:
        levels = sorted({lv for r in m["rows"] for lv in r["levels"] if lv})
        forms = [f for r in m["rows"] for f in r["forms"]]
        key = bundle.drug(m["name"])
        entry = merged.setdefault(key, {"codes": [], "sections": [], "levels": [], "forms": [], "pages": []})
        entry["codes"].append(m["code"])
        entry["sections"].append(m["section"])
        entry["levels"] = sorted(set(entry["levels"]) | set(levels))
        have = {_key(f) for f in entry["forms"]}
        entry["forms"] += [f for f in forms if _key(f) not in have]
        entry["pages"].append(m["page"])
        bundle.drug(m["name"], nlem=entry)
        by_section.setdefault(m["section"], []).append(
            f"- {m['name']} ({m['code']}; levels {','.join(levels)}): {'; '.join(forms)}"
        )
    for sec, extra in notes.items():
        by_section.setdefault(sec, []).extend(f"Note: {n}" for n in extra)
    for sec, lines in by_section.items():
        bundle.passages(
            breadcrumb=f"NLEM 2022 › {sec}", body="\n".join(lines), section="essential_list", topic=sec,
        )
    bundle.stats["medicines"] = len(medicines)
    return bundle
