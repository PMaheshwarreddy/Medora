"""Any clinical guideline PDF with a text layer (national programme
guidelines, treatment manuals, formularies written as prose), read by code.

  1. Lines are rebuilt from words with their font size and weight
     (pdfplumber). A page whose words never cross its middle is two columns
     and is read left column first.
  2. Lines printed on many pages at the same place (running heads, footers,
     page numbers) are removed.
  3. Headings are lines clearly larger than the body text, or short bold
     lines; their level follows their size. Each heading path becomes the
     passage breadcrumb: "<source> › <chapter> › <section>".
  4. Tables (pdfplumber) become Markdown in the section they sit in; their
     words are left out of the running text.
  5. A page with almost no text layer (a scanned or image page) is read by
     Gemini vision with the same check as the ICMR posters: a box with a
     number not visible in the PDF is dropped. Without a Gemini key such
     pages are quarantined.

Nothing is paraphrased: passages are the PDF's own words, so no number can be
invented. Structured doses are not extracted from prose (too easy to attach a
dose to the wrong drug); the writer reads them in the passages.

Register a PDF in sources.py with reader "guideline", e.g.
  Source("nvbdcp-malaria-2014", "National Drug Policy on Malaria", "NVBDCP, MoHFW", "2013",
         "guideline", 1, "Government of India publication", True,
         ("medora_5/malaria_drug_policy.pdf",), "guideline")
"""

import asyncio
import re
from collections import Counter
from pathlib import Path

import pdfplumber

from ..checks import unknown_numbers
from ..load import Bundle
from ..sources import Source
from ..text import clean, normalize, words

# "2.1 Clinical features" is a heading; "2. Primaquine: 0.75 mg/kg" is a list item
_NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,3})\.?\s+[A-Z][^:]*$")
_REFERENCES = re.compile(r"^\s*(\d+(\.\d+)*\.?\s+)?(references?|bibliography|further reading|acknowledg\w*|abbreviations?|annex(ure)?\s*[-–:]?\s*contributors)\b", re.I)
# "Page 65 / 409", "Page 11 9/ 409" (a web export's footer, spacing broken)
_PAGE_FOOTER = re.compile(r"^page\s*[\d\s]+/\s*\d+$", re.I)
MIN_TEXT_WORDS = 40  # below this a page is treated as an image page
HEADER_SHARE = 0.3  # a line on this share of pages is a running head or footer

_KINDS = (
    (re.compile(r"(prevent|prophyla|vaccin|vector control)\w*", re.I), "prevention"),
    (re.compile(r"\b(danger|warning|red flag|emergency sign|alarm)\b", re.I), "red_flags"),
    (re.compile(r"\b(refer|referral)\b", re.I), "referral"),
    (re.compile(r"\b(investigation|diagnos|laborator|test)\w*", re.I), "investigations"),
    (re.compile(r"\b(clinical feature|symptom|sign|presentation|case definition|when to suspect)\w*", re.I), "suspect"),
    (re.compile(r"\b(dose|dosage|regimen|drug|medicine|treatment|management|therapy)\w*", re.I), "treatment"),
)

VISION_PROMPT = """This image is one page of a clinical guideline. Transcribe it into structured JSON.
Rules: copy the page's words exactly; never add facts, numbers, drugs or doses; skip logos and page furniture;
flowcharts as lines with "->" between steps; tables as Markdown tables with their header row.
Return: {"title": "the page's main heading or topic", "page_kind": "content" | "front_matter" | "other",
 "sections": [{"heading": "...", "markdown": "..."}]}"""


def _kind(heading: str) -> str:
    for pattern, kind in _KINDS:
        if pattern.search(heading):
            return kind
    return "other"


def _lines(page) -> list[dict]:
    """[{top, x0, size, bold, text}] in reading order, tables removed."""
    # A page saved from a web browser (the MSF guidelines) has one invisible
    # box around the whole page, reaching far past its edges; read as a
    # table it would swallow every word. A real table lies on the page.
    tables = [t for t in page.find_tables()
              if t.bbox[1] >= -2 and t.bbox[3] <= page.height + 2 and t.bbox[0] >= -2 and t.bbox[2] <= page.width + 2]
    boxes = [t.bbox for t in tables]

    def in_table(w) -> bool:
        return any(b[0] - 1 <= w["x0"] and w["x1"] <= b[2] + 1 and b[1] - 1 <= w["top"] and w["bottom"] <= b[3] + 1 for b in boxes)

    ws = [w for w in page.extract_words(x_tolerance=1.5, extra_attrs=["size", "fontname"]) if not in_table(w)]
    mid = page.width / 2
    crossing = sum(1 for w in ws if w["x0"] < mid - 4 and w["x1"] > mid + 4)
    columns = [ws]
    if ws and crossing / len(ws) < 0.02 and sum(w["x0"] > mid for w in ws) > len(ws) * 0.25:
        columns = [[w for w in ws if w["x1"] <= mid + 4], [w for w in ws if w["x1"] > mid + 4]]
    out = []
    for col in columns:
        rows: dict[int, list] = {}
        for w in col:
            rows.setdefault(round(w["top"] / 2.5), []).append(w)
        for key in sorted(rows):
            row = sorted(rows[key], key=lambda w: w["x0"])
            sizes = [w["size"] for w in row]
            out.append({
                "top": row[0]["top"], "x0": row[0]["x0"], "size": max(set(sizes), key=sizes.count),
                "bold": sum("bold" in w["fontname"].lower() or "black" in w["fontname"].lower() for w in row) > len(row) / 2,
                "text": " ".join(w["text"] for w in row),
            })
    # each table as Markdown, at its place on the page
    for t in tables:
        rows = [[clean(c or "").replace("\n", " ") for c in r] for r in t.extract() if any(c for c in r)]
        if len(rows) >= 2:
            head = "| " + " | ".join(rows[0]) + " |\n|" + "---|" * len(rows[0])
            body = "\n".join("| " + " | ".join(r) + " |" for r in rows[1:])
            out.append({"top": t.bbox[1], "x0": t.bbox[0], "size": 0, "bold": False, "text": head + "\n" + body, "table": True})
    out.sort(key=lambda ln: (ln["x0"] > mid + 4 and len(columns) == 2, ln["top"]))
    return out


def _diagram(lines: list[dict]) -> bool:
    """A flowchart or decision chart: many lines of a few words each, which
    read as jumbled fragments. Such pages go to the vision reader."""
    text_lines = [ln for ln in lines if not ln.get("table")]
    if len(text_lines) < 25:
        return False
    lengths = sorted(len(ln["text"].split()) for ln in text_lines)
    return lengths[len(lengths) // 2] <= 4


def _furniture(pages: list[list[dict]]) -> set[str]:
    """Lines repeated across pages: running heads, footers, page numbers."""
    def key(text: str) -> str:
        return re.sub(r"\d+", "#", normalize(text))

    counts = Counter(k for lines in pages for k in {key(ln["text"]) for ln in lines if len(ln["text"]) < 120})
    limit = max(3, len(pages) * HEADER_SHARE)
    return {k for k, n in counts.items() if n >= limit or k in ("#", "")}


async def _vision_pages(numbers: list[int], pdf_path: Path, settings) -> dict[int, dict | BaseException]:
    import pypdfium2 as pdfium
    from google import genai

    from .stw import CONCURRENCY, _page_image, _vision

    pdf = pdfium.PdfDocument(str(pdf_path))
    client = genai.Client(api_key=settings.gemini_api_key)
    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*(_vision(client, _page_image(pdf[n - 1]), sem, base=VISION_PROMPT) for n in numbers),
                                   return_exceptions=True)
    return dict(zip(numbers, results))


def read(source: Source, paths: list[Path], settings=None, **_) -> Bundle:
    bundle = Bundle()
    # the breadcrumb's first part: "MSF Clinical guidelines" from
    # "MSF Clinical guidelines: diagnosis and treatment manual"
    head = source.title.split(":")[0].strip()
    short = source.title if len(source.title) <= 50 else head if len(head) <= 50 else source.key
    # A formulary (drug monographs) answers "how is it treated" only: its
    # passages are drug reference material, which pass 1 leaves out.
    drug_book = source.kind == "formulary"
    for path in paths:
        with pdfplumber.open(path) as pdf:
            pages = [_lines(p) for p in pdf.pages]
            texts = [p.extract_text() or "" for p in pdf.pages]
            pictures = [len(p.images) for p in pdf.pages]
        furniture = _furniture(pages)
        body_sizes = Counter(round(ln["size"]) for lines in pages for ln in lines if not ln.get("table") and ln["size"])
        body = body_sizes.most_common(1)[0][0] if body_sizes else 10
        heading_sizes = sorted({round(ln["size"]) for lines in pages for ln in lines if ln["size"] >= body + 1.5}, reverse=True)
        level_of = {size: min(i + 1, 3) for i, size in enumerate(heading_sizes)}

        path_titles: dict[int, str] = {}
        current: list[str] = []
        section_page = 1
        image_pages: list[int] = []
        skipping = False

        def flush() -> None:
            if not current:
                return
            text = "\n".join(current).strip()
            current.clear()
            if len(text.split()) < 12:
                return
            crumbs = [path_titles[k] for k in sorted(path_titles)]
            kind = _kind(" ".join(crumbs))
            bundle.passages(breadcrumb=" › ".join([short, *crumbs]), body=text,
                            section=f"drug:monograph_{kind}" if drug_book else kind,
                            topic=crumbs[0] if crumbs else short, page=section_page)
            bundle.stats["sections"] += 1

        for number, lines in enumerate(pages, start=1):
            content = [ln for ln in lines if re.sub(r"\d+", "#", normalize(ln["text"])) not in furniture]
            # a scanned page (little text, a picture) or a chart goes to the
            # vision reader; a short page of text (contents, footnotes, the
            # end of a chapter) is read as text
            few_words = len(words(" ".join(ln["text"] for ln in content))) < MIN_TEXT_WORDS
            if few_words and not pictures[number - 1] and not _diagram(content):
                if not content:
                    bundle.stats["blank pages skipped"] += 1
                    continue
            elif few_words or _diagram(content):
                image_pages.append(number)
                continue
            bundle.add("kb_pages", page=number, page_kind="text", title="", markdown="", checks={}, status="ok")
            for ln in content:
                text = clean(ln["text"])
                if _PAGE_FOOTER.match(text):
                    continue
                if ln.get("table"):
                    current.append(text)
                    continue
                size = round(ln["size"])
                numbered = _NUMBERED.match(text)
                short_line = len(text.split()) <= 12 and not text.endswith((".", ",", ";")) and ":" not in text[:-1]
                is_heading = (
                    size in level_of
                    or (ln["bold"] and short_line and not re.match(r"^\d+\.\s", text))
                    or (numbered and short_line and size >= body)
                )
                if is_heading and len(text) < 160 and re.search(r"[A-Za-z]{3}", text):
                    flush()
                    skipping = bool(_REFERENCES.match(text))
                    level = level_of.get(size) or (min(numbered.group(1).count(".") + 1, 3) if numbered else 3)
                    for k in [k for k in path_titles if k >= level]:
                        del path_titles[k]
                    path_titles[level] = text.title() if text.isupper() else text
                    section_page = number
                    continue
                if skipping:
                    continue  # reference lists and acknowledgements are not clinical text
                if not current:
                    section_page = number
                if current and not current[-1].startswith("|") and current[-1].endswith("-") and text[:1].islower():
                    current[-1] = current[-1][:-1] + text
                else:
                    current.append(text)
        flush()

        if image_pages:
            if settings is None or not getattr(settings, "gemini_api_key", ""):
                for n in image_pages:
                    bundle.add("kb_pages", page=n, page_kind="image", title="", markdown="", checks={}, status="quarantined")
                    bundle.refuse({"page": n}, "image page: no text layer and no Gemini key to read it", n)
            else:
                readings = asyncio.run(_vision_pages(image_pages, path, settings))
                for n, data in readings.items():
                    if isinstance(data, BaseException):
                        own = [ln for ln in texts[n - 1].split("\n") if ln.strip() and not _PAGE_FOOTER.match(ln.strip())]
                        if len(words(" ".join(own))) >= MIN_TEXT_WORDS:
                            # the model could not read it, but the page has its
                            # own text layer: keep those exact words
                            title = clean(own[0])[:120]
                            kind = _kind(title + " " + " ".join(own[:6]))
                            bundle.passages(breadcrumb=f"{short} › {title}", body="\n".join(clean(x) for x in own[1:]),
                                            section=f"drug:monograph_{kind}" if drug_book else kind, topic=title, page=n)
                            bundle.add("kb_pages", page=n, page_kind="image", title=title, markdown="",
                                       checks={"vision_error": str(data)[:200], "read": "text layer"}, status="ok")
                            bundle.stats["chart pages kept as their text layer"] += 1
                            continue
                        bundle.add("kb_pages", page=n, page_kind="image", title="", markdown="",
                                   checks={"error": str(data)[:300]}, status="pending")
                        continue
                    if (data.get("page_kind") or "content") != "content":
                        bundle.add("kb_pages", page=n, page_kind=data.get("page_kind", "other"), title="", markdown="",
                                   checks={}, status="skipped")
                        continue
                    page_text = texts[n - 1]
                    kept = 0
                    for sec in data.get("sections") or []:
                        heading, text = clean(sec.get("heading", "")), clean(sec.get("markdown", ""))
                        if not text:
                            continue
                        # every number must be in the page's own text layer; a page with no
                        # text layer at all can only give boxes without numbers
                        extra = unknown_numbers(text, page_text)
                        if extra:
                            reason = (f"numbers not on the page: {sorted(extra)[:8]}" if page_text.strip()
                                      else "scanned page: its numbers cannot be checked")
                            bundle.refuse({"page": n, "section": heading}, reason, n)
                            continue
                        title = clean(data.get("title", "")) or short
                        bundle.passages(breadcrumb=f"{short} › {title} › {heading}", body=text, section=_kind(heading),
                                        topic=title, page=n)
                        kept += 1
                    bundle.add("kb_pages", page=n, page_kind="image", title=clean(data.get("title", "")),
                               markdown="", checks={"boxes_kept": kept}, status="ok" if kept else "quarantined")
        bundle.stats["image pages"] += len(image_pages)
    return bundle
