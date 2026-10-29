"""National Formulary of India 2011, read by code (no model).

- Monographs (pages 39-660): a drug name at the left margin, optional
  "Pregnancy Category-X" / "Schedule H", then labelled fields (Indications,
  Availability, Dose, Contraindications, Precautions, Adverse Effects,
  Storage) with their text in a right-hand column.
- Appendix 6c: drug interactions, an UPPER CASE drug followed by rows
  "other drug | effect".
- Chapter introductions and the other appendices: passages.

Lines are rebuilt from word positions (pdfplumber), so a label and its value
are told apart by the gap between them, not by spacing in extracted text.
"""

import re
from pathlib import Path

import pdfplumber

from ..checks import unknown_numbers
from ..load import Bundle
from ..sources import Source
from ..text import clean

FIRST_MONOGRAPH_PAGE, APPENDIX_PAGE, INTERACTIONS = 39, 661, range(685, 733)
END_PAGE = 785  # index and feedback form follow
GAP = 12  # points between words that separate a label from its value

LABELS = {
    "indications": "indications", "availability": "availability", "dose": "dose",
    "contraindications": "contraindications", "precautions": "precautions", "adverse effects": "adverse_effects",
    "storage": "storage",
}
# Appendix tables "drug | advice": running head -> kb_drug_safety kind
APPENDIX_TABLES = {"Appendix 7a": "hepatic", "Appendix 7b": "lactation", "Appendix 7c": "pregnancy", "Appendix 7d": "renal"}
SAFETY = {"contraindications": "contraindication", "precautions": "precaution", "adverse_effects": "adverse"}
_PREG = re.compile(r"Pregnancy\s+Category\s*[-–:]?\s*([ABCDX])\b", re.I)
_SCHED = re.compile(r"\bSchedule\s+(H1|H|X|G)\b")
_FOOTER = re.compile(r"^(NFI-2011\s*\d*|\d+\s*NFI-2011|[ivxlcXVILC]+\s*NFI-2011|NFI-2011\s*[ivxlcXVILC]+)$")
_ROUTE = re.compile(r"^(Oral|Intravenous|Intramuscular|Subcutaneous|Topical|Inhalation|Rectal|Ophthalmic|Intrathecal|Intradermal|Vaginal|Nasal|Sublingual)", re.I)


def lines_of(page) -> list[tuple[float, list[tuple[float, str]]]]:
    """[(x of first word, [(x, segment text), ...])] top to bottom."""
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5)
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) < 3:
            rows[-1].append(w)
        else:
            rows.append([w])
    out = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        segs: list[list] = []
        for w in row:
            if segs and w["x0"] - segs[-1][2] < GAP:
                segs[-1][1] += " " + w["text"]
                segs[-1][2] = w["x1"]
            else:
                segs.append([w["x0"], w["text"], w["x1"]])
        out.append((segs[0][0], [(s[0], s[1]) for s in segs]))
    return out


def _join(parts: list[str]) -> str:
    text = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if text.endswith("-") and p[:1].islower():
            text = text[:-1] + p
        else:
            text = f"{text} {p}" if text else p
    return clean(text)


class _Monograph:
    def __init__(self, name: str, chapter: str, page: int):
        self.name, self.chapter, self.page = name, chapter, page
        self.fields: dict[str, list[str]] = {}
        self.preg = self.sched = ""
        self.field: str | None = None
        self.value_x = 0.0


_LABEL_FAMILY = re.compile(
    r"^(?:(indications?)|(ava\w*)|(dos(?:e|age)s?)|(contra-?indications?)|(precautions?)|(adverse (?:effects?|reactions?))|(storage))$"
)
_FAMILY_KEYS = ("indications", "availability", "dose", "contraindications", "precautions", "adverse_effects", "storage")


def _label(text: str) -> str | None:
    """The field a label names, spelling slips included ('Avaialbility:', 'Dosage:')."""
    m = _LABEL_FAMILY.match(text.strip().rstrip(":").strip().lower())
    if not m:
        return None
    return _FAMILY_KEYS[next(i for i, g in enumerate(m.groups()) if g)]


_LABEL_PREFIX = re.compile(
    r"^(Indications?|Ava\w*:?|Dos(?:e|age):?|Contra-?indications?|Precautions?|Adverse (?:[Ee]ffects?|[Rr]eactions?)|Storage)\s+(\S.*)$"
)
_NUMBERED = re.compile(r"^\d+(\.\d+)*\.?\s")
_REFER = re.compile(r"\(\s*Refer\s+page.*?\)", re.I)


def _split_label(segs: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """'Contraindications Porphyria.' printed without a gap -> label, value."""
    m = _LABEL_PREFIX.match(segs[0][1])
    if not m:
        return segs
    x = segs[0][0]
    return [(x, m.group(1)), (x + 66, m.group(2)), *segs[1:]]


def _name(pending: list[str]) -> str:
    """The drug name from the short lines before the labels (headings dropped)."""
    lines = [p for p in pending if not _NUMBERED.match(p) and not p.replace(" ", "").isdigit()]
    if not lines:
        return ""
    name = lines[-1]
    if len(lines) > 1 and lines[-2].rstrip().endswith(("+", "(", "and")):
        name = f"{lines[-2]} {name}"
    name = _REFER.sub("", name)
    return re.sub(r"\s+", " ", name).strip(" *")


def read(source: Source, paths: list[Path], **_) -> Bundle:
    bundle = Bundle()
    monographs: list[_Monograph] = []
    prose: dict[str, list[tuple[int, str]]] = {}
    interactions: dict[str, list[list[str]]] = {}
    appendix: dict[str, list] = {}
    header_starts: dict[str, list[float]] = {}
    with pdfplumber.open(paths[0]) as pdf:
        page_texts = {}
        current: _Monograph | None = None
        pending: list[str] = []
        meta = ("", "")
        drug_head = ""
        for number in range(27, END_PAGE):
            page = pdf.pages[number - 1]
            lines = lines_of(page)
            page_texts[number] = " ".join(s for _, segs in lines for _, s in segs)
            lines = [ln for ln in lines if not _FOOTER.match(" ".join(s for _, s in ln[1]).strip())]
            if not lines:
                continue
            chapter = " ".join(s for _, s in lines[0][1]).strip()
            lines = lines[1:]  # running head
            left = min((x for x, _ in lines), default=0)

            if chapter in APPENDIX_TABLES:
                kind = APPENDIX_TABLES[chapter]
                rows = appendix.setdefault(kind, [])
                starts = _table_rows(page, rows, header_starts.get(kind), prose.setdefault(chapter, []), number)
                if starts:
                    header_starts[kind] = starts
                continue

            if number in INTERACTIONS:
                for x, segs in lines:
                    text = " ".join(s for _, s in segs)
                    if len(segs) == 1 and x < left + 5 and text.isupper() and len(text) > 2:
                        drug_head = text.title()
                        interactions.setdefault(drug_head, [])
                    elif drug_head and len(segs) >= 2 and x < left + 5:
                        interactions[drug_head].append([segs[0][1], " ".join(s for _, s in segs[1:]), number])
                    elif drug_head and interactions[drug_head]:
                        row = interactions[drug_head][-1]
                        if x < left + 5:
                            row[0] += " " + text
                        else:
                            row[1] = _join([row[1], text])
                continue

            for x, segs in lines:
                segs = _split_label(segs)
                text = " ".join(s for _, s in segs)
                if number >= FIRST_MONOGRAPH_PAGE and number < APPENDIX_PAGE:
                    label = _label(segs[0][1])
                    if label and x < left + 10:
                        if current is None and label != "indications" and monographs and monographs[-1].page >= number - 1 \
                                and label not in monographs[-1].fields:
                            current = monographs[-1]  # the entry continues after a break
                        if current is None or (label == "indications" and "indications" in current.fields):
                            name = _name(pending)
                            current = _Monograph(name, chapter, number)
                            current.preg, current.sched = meta
                            monographs.append(current)
                            pending, meta = [], ("", "")
                        current.field = label
                        current.value_x = segs[1][0] if len(segs) > 1 else current.value_x or x + 60
                        current.fields.setdefault(label, []).append(" ".join(s for _, s in segs[1:]))
                        continue
                    if current and current.field and x > left + 30:
                        current.fields[current.field].append(text)
                        continue
                    m_p, m_s = _PREG.search(text), _SCHED.search(text)
                    if (m_p or m_s) and len(text) < 60:
                        # belongs to the monograph about to start
                        meta = (meta[0] or (m_p.group(1) if m_p else ""), meta[1] or (m_s.group(1) if m_s else ""))
                        continue
                    # a short line at the margin: a drug name, if labels follow
                    if current is not None and current.field:
                        current.field = None
                        current = None
                    if len(text) < 70 and not text.endswith((".", ",", ";")):
                        pending.append(text)
                        if len(pending) > 3:
                            prose.setdefault(chapter, []).append((number, pending.pop(0)))
                    else:
                        prose.setdefault(chapter, []).extend((number, p) for p in pending)
                        pending = []
                        prose.setdefault(chapter, []).append((number, text))
                    continue
                prose.setdefault(chapter, []).append((number, text))
    _emit_monographs(bundle, monographs, page_texts)
    _emit_interactions(bundle, interactions)
    _emit_appendix(bundle, appendix)
    for chapter, items in prose.items():
        body = _join([t for _, t in items])
        if len(body) > 200:
            bundle.passages(breadcrumb=f"NFI 2011 › {chapter}", body=_paragraphs(body), section="drug:chapter_text",
                            topic=chapter, page=items[0][0])
    return bundle


def _paragraphs(body: str) -> str:
    # sentence groups of about 60 words, so the chunker has places to split
    sentences = re.split(r"(?<=[.;:])\s+(?=[A-Z])", body)
    out, cur = [], []
    for s in sentences:
        cur.append(s)
        if sum(len(x.split()) for x in cur) > 60:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return "\n".join(out)


def _emit_monographs(bundle: Bundle, monographs: list[_Monograph], page_texts: dict[int, str]) -> None:
    for m in monographs:
        fields = {k: _join(v) for k, v in m.fields.items()}
        name = re.sub(r"\s*\*+$", "", _PREG.sub("", _SCHED.sub("", m.name))).strip(" *-")
        if not name or "indications" not in fields:
            bundle.refuse({"name": m.name, "fields": list(fields)}, "monograph without a name or indications", m.page)
            continue
        source_text = page_texts.get(m.page, "") + " " + page_texts.get(m.page + 1, "") + " " + page_texts.get(m.page + 2, "")
        extra = unknown_numbers(fields.get("dose", ""), source_text)
        if extra:
            bundle.refuse({"name": name, "dose": fields.get("dose")}, f"dose numbers not on the page: {sorted(extra)}", m.page)
            fields.pop("dose", None)
        preg, sched = m.preg, m.sched
        bundle.drug(name, drug_class=m.chapter, schedule=sched, pregnancy_category=preg, nfi_page=m.page)
        if fields.get("dose"):
            route = _ROUTE.match(fields["dose"])
            bundle.add("kb_doses", page=m.page, drug=name, indication=fields.get("indications", "")[:500],
                       population="any", dose=fields["dose"], route=route.group(1).lower() if route else "",
                       frequency="", duration="", chunk_hash="")
        for key, kind in SAFETY.items():
            if fields.get(key):
                bundle.add("kb_drug_safety", page=m.page, drug=name, kind=kind, body=fields[key])
        lines = [f"{m.name.strip()}" + (f" (Pregnancy category {preg})" if preg else "") + (f" (Schedule {sched})" if sched else "")]
        for key in ("indications", "availability", "dose", "contraindications", "precautions", "adverse_effects", "storage"):
            if fields.get(key):
                lines.append(f"{key.replace('_', ' ').capitalize()}: {fields[key]}")
        hashes = bundle.passages(breadcrumb=f"NFI 2011 › {m.chapter} › {name}", body="\n".join(lines),
                                 section="drug:monograph", topic=name, page=m.page)
        if fields.get("dose") and hashes:
            bundle.rows["kb_doses"][-1]["chunk_hash"] = hashes[0]
        bundle.stats["monographs"] += 1


_APPENDIX_TITLES = {"hepatic": "Liver disease (Appendix 7a)", "lactation": "Breast-feeding (Appendix 7b)",
                    "pregnancy": "Pregnancy (Appendix 7c)", "renal": "Kidney disease, dose by GFR (Appendix 7d)"}


def _cell_starts(lines: list[list[dict]], first_x: float) -> list[float]:
    """Column starts: the x where cells begin again and again on this page
    (each row's first word in a column), merged within 8 points."""
    from collections import Counter

    counts = Counter()
    for line in lines:
        prev_x1 = None
        for w in line:
            if prev_x1 is None or w["x0"] - prev_x1 > 4:
                counts[round(w["x0"] / 3) * 3] += 1
            prev_x1 = w["x1"]
    peaks = sorted(x for x, n in counts.items() if n >= 5 and x >= first_x - 4)
    starts: list[float] = []
    for x in peaks:
        if not starts or x - starts[-1] > 8:
            starts.append(x)
    return starts if len(starts) >= 2 else [first_x]


def _table_rows(page, rows: list, starts: list[float] | None, prose: list, number: int) -> list[float] | None:
    """Reads one page of a 'Drug | ... ' appendix table word by word: the
    header row ('Drug', 'Status', 'Comments' ...) gives each column's x, every
    word goes to its column, and a row starts where the Drug column has a word
    starting with a capital. Returns the header's column starts (kept for the
    next page, which may print no header)."""
    words = page.extract_words(x_tolerance=1.5)
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w["top"] / 3), []).append(w)
    ordered = [sorted(lines[k], key=lambda w: w["x0"]) for k in sorted(lines)]
    found = None
    for line in ordered[1:]:  # first line is the running head
        texts = [w["text"] for w in line]
        if texts and texts[0] == "Drug" and len(texts) >= 2:
            found = starts = _cell_starts(ordered, line[0]["x0"])
            rows.append(None)
            continue
        if texts and texts[0] in ("Method", "min)", "(ml/min)"):
            continue  # the rest of a multi-line header
        if not starts:
            prose.append((number, " ".join(texts)))
            continue
        if _FOOTER.match(" ".join(texts)):
            continue
        cells: list[list[str]] = [[] for _ in starts]
        for w in line:
            col = max(i for i, x in enumerate(starts) if w["x0"] >= x - 4) if w["x0"] >= starts[0] - 4 else 0
            cells[col].append(w["text"])
        first = " ".join(cells[0])
        if len(" ".join(texts)) > 60 and not any(cells[1:]):
            prose.append((number, " ".join(texts)))  # a paragraph under the table
            rows.append(None)
            continue
        if first[:1].isupper() and cells[1]:  # a new drug: a name and a value right of it
            rows.append([[[" ".join(c)] if c else [] for c in cells], number])
        elif rows and rows[-1] is not None:
            for i, c in enumerate(cells):
                if c:
                    rows[-1][0][i].append(" ".join(c))
    return found


_APPENDIX_COLUMNS = {
    "hepatic": ["Status", "Comment"],
    "lactation": ["Comment"],
    "renal": ["Dose method (D = dose, I = interval)", "GFR >50", "GFR 10-50", "GFR <10", "CAPD", "Haemodialysis"],
}


def _emit_appendix(bundle: Bundle, appendix: dict[str, list]) -> None:
    for kind, rows in appendix.items():
        lines = []
        for row in rows:
            if row is None:
                continue
            cells, page = row
            name = _join(cells[0]).rstrip("-")
            values = [_join(c) for c in cells[1:]]
            heads = _APPENDIX_COLUMNS.get(kind, [])
            if len(heads) == len(values):
                body = "; ".join(f"{h}: {v}" for h, v in zip(heads, values) if v)
            else:
                body = " | ".join(v for v in values if v)
            if not name or not body or name.lower() in ("drug", "drugs", "medicine"):
                continue
            bundle.add("kb_drug_safety", page=page, drug=name, kind=kind, body=body)
            lines.append(f"- {name}: {body}")
        if lines:
            bundle.passages(breadcrumb=f"NFI 2011 › {_APPENDIX_TITLES[kind]}", body="\n".join(lines),
                            section=f"drug:{kind}", topic=_APPENDIX_TITLES[kind])
        bundle.stats[f"appendix {kind} rows"] = len(lines)


def _emit_interactions(bundle: Bundle, interactions: dict[str, list[list[str]]]) -> None:
    for drug, rows in interactions.items():
        if not rows:
            continue
        lines = []
        for other, effect, page in rows:
            other, effect = clean(other), clean(effect)
            if not other or not effect:
                continue
            bundle.add("kb_drug_safety", page=page, drug=drug, kind="interaction", body=f"With {other}: {effect}")
            lines.append(f"- {other}: {effect}")
        if lines:
            bundle.passages(breadcrumb=f"NFI 2011 › Drug interactions › {drug}", body="\n".join(lines),
                            section="drug:interactions", topic=drug, page=rows[0][2])
            bundle.stats["interaction drugs"] += 1
