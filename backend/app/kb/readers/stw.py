"""ICMR Standard Treatment Workflows: one-page infographic posters.

Plain text extraction scrambles these (boxes, columns, flowchart arrows), so
each poster page is read twice and the two readings are checked against each
other:

- Gemini (vision) reads the page image into sections, doses and red flags:
  it understands the layout but may misread or invent.
- The PDF's own text layer holds the exact characters but not the layout.

A page is loaded only if every number in the vision reading is in the text
layer and the reading covers most of the page's words; otherwise the whole
page is quarantined. Doses are checked one by one again (a real medicine, an
amount with a unit, numbers on the page). Vision results are cached by page
image, so a re-run costs no model calls.
"""

import asyncio
import hashlib
import io
import json
import logging
import re
from collections import Counter
from pathlib import Path

import pypdfium2 as pdfium

from ..checks import MIN_COVERAGE, coverage, dose_problem, unknown_numbers
from ..load import Bundle
from ..sources import Source
from ..text import clean, words

log = logging.getLogger("medora.kb.stw")

MODEL = "gemini-2.5-flash"
# A reading that invents no number but leaves some text out still loads,
# marked partial, down to this share of the page's words.
PARTIAL_COVERAGE = 0.80
PROMPT_VERSION = "stw-1"
CONCURRENCY = 4
CACHE = Path(__file__).resolve().parents[3] / "data/kb_cache/vision"
_ICD = re.compile(r"\bICD[- ]?1[01]\b", re.I)
_TITLE_PREFIX = re.compile(
    r"^((standard treatment workflow\s*(\(stw\))?\s*)?(for\s+)?(the\s+)?((management|approach)\s+(of|to)\s+)?)", re.I
)
_REFERENCES = re.compile(r"^\s*(references?|bibliography|further reading|abbreviations?)\b", re.I)
_SKIP_HEADINGS = re.compile(r"\b(contents|foreword|preface|message|acknowledg|editorial board|expert committee|"
                            r"suggested citation|all rights reserved|abbreviations)\b", re.I)

PROMPT = """This image is one page of the Indian Council of Medical Research "Standard Treatment Workflows" (STW): an infographic poster with boxes, columns, tables and flowcharts.

Transcribe it into structured JSON. Rules:
- Copy the page's words exactly. Never add facts, numbers, drugs or doses that are not printed on the page. Never fix or complete anything.
- Keep every clinical statement. Skip only logos, the ministry header, the date stamp and the standard disclaimer paragraph at the bottom.
- Flowcharts: write each path as a line using "->" between steps, keeping the branch labels.
- Tables: Markdown tables with their header row.
- A box's heading becomes a section; its bullets stay bullets.

Return:
{
 "title": "the condition or topic in the page title",
 "codes": ["ICD codes printed, e.g. A90"],
 "page_kind": "workflow" | "front_matter" | "contents" | "other",
 "sections": [{"heading": "...", "type": "suspect|red_flags|assessment|investigations|treatment|drugs|referral|prevention|discharge|other", "level": "primary|secondary|tertiary|any", "markdown": "..."}],
 "doses": [{"drug": "...", "dose": "as printed", "route": "", "frequency": "", "duration": "", "population": "adult|child|neonate|any", "indication": "what it is given for, as printed"}],
 "red_flags": [{"sign": "as printed", "action": "what the page says to do, as printed, or empty"}]
}
doses: only medicines or fluids printed with an amount on this page. red_flags: warning signs, danger signs, emergency or referral criteria."""


_SHORTER = ("\n\nAn earlier answer for this page was cut off or repeated itself. Keep each section's markdown "
            "under 2000 characters, never repeat a line, and close every string.")


def _page_image(page) -> bytes:
    w, h = page.get_size()
    scale = min(2.0, 3000 / max(w, h))  # Gemini reads up to about 3000 px
    buf = io.BytesIO()
    page.render(scale=scale).to_pil().convert("RGB").save(buf, "JPEG", quality=88)
    return buf.getvalue()


async def _vision(client, image: bytes, semaphore: asyncio.Semaphore, note: str = "", base: str | None = None) -> dict:
    """One reading of a page image. `note` asks a second reading to fix what
    the checks found missing. Broken or runaway JSON gets one more try at a
    different temperature."""
    from google.genai import types

    from ...llm import with_retries

    base = PROMPT if base is None else base
    # The STW prompt keeps its old cache keys (no re-reading of 241 pages).
    salt = b"" if base is PROMPT else hashlib.sha256(base.encode()).digest()
    key = hashlib.sha256(image + PROMPT_VERSION.encode() + note.encode() + salt).hexdigest()
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    prompt = base + (f"\n\n{note}" if note else "")
    async with semaphore:
        data = None
        attempts = ((0.0, prompt), (0.4, prompt), (0.2, prompt + _SHORTER))
        for temperature, text_prompt in attempts:
            async def call(t=temperature, tp=text_prompt):
                r = await client.aio.models.generate_content(
                    model=MODEL,
                    contents=[types.Part.from_bytes(data=image, mime_type="image/jpeg"), tp],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json", temperature=t, max_output_tokens=16384,
                        thinking_config=types.ThinkingConfig(thinking_budget=1024),
                    ),
                )
                return json.loads(r.text)

            try:
                data = await with_retries(call, "STW page reading")
                break
            except (ValueError, TypeError) as e:  # invalid JSON, or an empty answer
                last = e
        if data is None:
            raise last
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data


def _boilerplate(texts: list[str]) -> set[str]:
    """Words on most pages of the volume: header, footer, disclaimer."""
    counts = Counter(w for t in texts for w in set(words(t)))
    return {w for w, n in counts.items() if n >= max(3, len(texts) * 0.6)}


def _transcript(data: dict) -> str:
    parts = [data.get("title", ""), " ".join(data.get("codes") or [])]
    for s in data.get("sections") or []:
        parts += [s.get("heading", ""), s.get("markdown", "")]
    for d in data.get("doses") or []:
        parts += [str(v) for v in d.values()]
    for f in data.get("red_flags") or []:
        parts += [f.get("sign", ""), f.get("action", "")]
    return "\n".join(p for p in parts if p)


def _check(data: dict, content: str, text: str) -> dict:
    transcript = _transcript(data)
    return {
        "coverage": round(coverage(transcript, content), 3),
        "unknown_numbers": sorted(unknown_numbers(transcript, text)),
    }


def _score(checks: dict) -> tuple:
    passed = checks["coverage"] >= PARTIAL_COVERAGE and not checks["unknown_numbers"]
    return (passed, -len(checks["unknown_numbers"]), checks["coverage"])


def _correction(data: dict, content: str, checks: dict) -> str:
    got = set(words(_transcript(data)))
    missing = sorted({w for w in words(content) if len(w) >= 4 and w not in got})[:80]
    lines = ["A first reading of this page was checked against the PDF's own text and failed:"]
    if missing:
        lines.append("- These words are printed on the page but were left out: " + ", ".join(missing)
                     + ". Transcribe every box, table and footnote, including these.")
    if checks["unknown_numbers"]:
        lines.append("- These numbers are NOT printed on the page and must not appear: " + ", ".join(checks["unknown_numbers"])
                     + ". Do not number lists; copy numbers exactly as printed.")
    lines.append("In doses, write the amount exactly as printed (never the words 'as printed').")
    return "\n".join(lines)


def _title(raw: str) -> str:
    """'Standard Treatment Workflow (STW) for the Management of DENGUE FEVER' -> 'Dengue Fever'."""
    t = clean(raw).replace("\n", " ")
    t = _TITLE_PREFIX.sub("", t).strip(" :-–") or t
    letters = [ch for ch in t if ch.isalpha()]
    upper = sum(ch.isupper() for ch in letters)
    if letters and upper > len(letters) * 0.6:
        t = t.title()
    elif re.search(r"\b[A-Z]{4,}\b", t):  # 'Management of DEPRESSION' style: title-case the shouted words
        t = re.sub(r"\b[A-Z]{4,}\b", lambda m: m.group(0).title(), t)
    return t[:1].upper() + t[1:]


def _short(source: Source) -> str:
    vol = source.key.rsplit("-", 1)[-1].replace("vol", "Vol. ")
    return f"ICMR STW {source.edition} {vol}"


async def _read_all(source: Source, path: Path, settings) -> Bundle:
    from google import genai

    bundle = Bundle()
    pdf = pdfium.PdfDocument(str(path))
    texts = [clean(pdf[i].get_textpage().get_text_range()) for i in range(len(pdf))]
    common = _boilerplate(texts)
    todo: list[int] = []
    for i, t in enumerate(texts):
        # A poster names itself "Standard Treatment Workflow" or prints an ICD
        # code; it is always read, even with an "Abbreviations" box (15
        # posters were lost to that until 2026-10-27). Front matter is
        # recognised by its first lines only.
        poster = "Standard Treatment Workflow" in t[:600] or bool(_ICD.search(t[:800]))
        if len(words(t)) < 60 or (not poster and (_SKIP_HEADINGS.search(t[:150]) or i < 6)):
            bundle.add("kb_pages", page=i + 1, page_kind="front_matter", title="", markdown="", checks={}, status="skipped")
            continue
        todo.append(i)

    client = genai.Client(api_key=settings.gemini_api_key)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    images = {i: _page_image(pdf[i]) for i in todo}
    results = await asyncio.gather(*(_vision(client, images[i], semaphore) for i in todo), return_exceptions=True)

    for i, data in zip(todo, results):
        number, text = i + 1, texts[i]
        if isinstance(data, BaseException):
            bundle.add("kb_pages", page=number, page_kind="other", title="", markdown="",
                       checks={"error": str(data)[:300]}, status="pending")
            bundle.stats["pages not read (model unavailable; re-run later)"] += 1
            continue
        kind = data.get("page_kind") or "other"
        if kind != "workflow":
            bundle.add("kb_pages", page=number, page_kind=kind, title=clean(data.get("title") or ""), markdown="", checks={}, status="skipped")
            continue
        content = " ".join(w for w in words(text) if w not in common)
        checks = _check(data, content, text)
        if checks["coverage"] < MIN_COVERAGE or checks["unknown_numbers"]:
            # one second reading, told exactly what the first one got wrong
            try:
                second = await _vision(client, images[i], semaphore, _correction(data, content, checks))
                second_checks = _check(second, content, text)
                if _score(second_checks) > _score(checks):
                    data, checks = second, {**second_checks, "second_reading": True}
            except Exception as e:  # noqa: BLE001 - the first reading's verdict stands
                checks["second_reading_error"] = str(e)[:200]
        title = _title(data.get("title", ""))
        sections, dropped = [], []
        for sec in data.get("sections") or []:
            heading = clean(sec.get("heading", ""))
            body = clean(sec.get("markdown", ""))
            if not body or _REFERENCES.match(heading):
                continue
            extra = unknown_numbers(f"{heading} {body}", text)
            if extra:
                # this box has a number the page does not print: drop the box, keep the page
                dropped.append(heading)
                bundle.refuse({"title": title, "section": heading, "markdown": body[:1500]},
                              f"section dropped: numbers not on the page: {', '.join(sorted(extra)[:10])}", number)
                continue
            sections.append((heading, body, sec.get("type") or "other", sec.get("level") or ""))
        checks["sections_dropped"] = dropped
        markdown = "\n\n".join(f"## {h}\n{b}" for h, b, _, _ in sections)
        problems = []
        if checks["coverage"] < MIN_COVERAGE:
            checks["partial"] = True  # some text left out, nothing invented
        if checks["coverage"] < PARTIAL_COVERAGE:
            problems.append(f"reading covers {checks['coverage']:.0%} of the page's words")
        if not sections or len(dropped) > len(sections):
            problems.append(f"most boxes carry numbers not on the page ({len(dropped)} dropped)")
        if problems:
            bundle.add("kb_pages", page=number, page_kind=kind, title=title, markdown=markdown, checks=checks, status="quarantined")
            bundle.refuse({"title": title}, "; ".join(problems), number)
            bundle.stats["pages quarantined"] += 1
            continue
        bundle.add("kb_pages", page=number, page_kind=kind, title=title, markdown=markdown, checks=checks, status="ok")
        bundle.stats["pages loaded"] += 1
        if dropped:
            bundle.stats["boxes dropped for a number not on the page"] += len(dropped)

        codes = [c.replace("ICD-10-", "").replace("ICD-10 ", "").replace("ICD 10-", "").strip() for c in data.get("codes") or []]
        crumb = f"{_short(source)} › {title}" + (f" ({', '.join(codes)})" if codes else "")
        for heading, body, section, level in sections:
            label = heading.title() if heading.isupper() else heading
            suffix = f" [{level} care]" if level in ("primary", "secondary", "tertiary") else ""
            bundle.passages(breadcrumb=f"{crumb} › {label}{suffix}", body=body, section=section, topic=title, page=number)
        for d in data.get("doses") or []:
            problem = dose_problem(d, text)
            if problem:
                bundle.refuse(d, f"dose: {problem}", number)
                continue
            population = d.get("population") if d.get("population") in ("adult", "child", "neonate") else "any"
            bundle.add("kb_doses", page=number, drug=clean(d.get("drug", "")), indication=clean(d.get("indication", "")) or title,
                       population=population, dose=clean(d.get("dose", "")), route=clean(d.get("route", "")),
                       frequency=clean(d.get("frequency", "")), duration=clean(d.get("duration", "")), chunk_hash="")
        for f in data.get("red_flags") or []:
            sign = clean(f.get("sign", ""))
            if sign and not unknown_numbers(sign, text):
                bundle.add("kb_red_flags", page=number, topic=title, sign=sign, action=clean(f.get("action", "")))
    return bundle


def read(source: Source, paths: list[Path], settings, **_) -> Bundle:
    if not settings.gemini_api_key:
        raise RuntimeError("MEDORA_GEMINI_API_KEY is needed to read the STW posters")
    return asyncio.run(_read_all(source, paths[0], settings))
