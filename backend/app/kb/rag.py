"""The two retrieval passes of a report, and the dose check after it.

  understand -> PASS 1 -> specialist panel + chair -> PASS 2 -> report writer -> checks
                (what could this be: presentation,   (how is it treated: treatment,
                 red flags, tests, referral)           doses and safety for the
                                                       conditions the chair named)

Pass 1 can only ask "what could this be?": the conditions are not known yet.
Pass 2 asks about treatment for the conditions the panel actually concluded,
so the writer reads the doses that matter instead of doses for every
condition the symptoms might suggest.

After the writer, every medicine's dose is looked up: in the pass-2 passages
and the medicine's printed doses (kb_doses). The result is recorded for the
doctor (`doseEvidence`); it does not change which medicines are shown (that
rule waits for the user's decision).
"""

import logging
import re

from .retrieve import DIAGNOSIS, TREATMENT, Evidence, Retriever, dose_found, label

log = logging.getLogger("medora.kb.rag")

PASS1_K = 6
PASS2_PER_CONDITION = 4
PASS2_MAX = 12
PASS2_RERANK = 8  # cross-encoder pairs per condition (pass 2 searches up to 3 times)
PRINTED_PER_CONDITION = 6
PAGE_BOXES = 3  # treatment boxes added from the page of a condition's best guideline passage

# A box written for another patient group ("Male UTI" for a woman, a
# children's dose table for an adult) is not evidence for this patient.
_GROUP_WORDS = {
    "male": re.compile(r"\b(males?|men|man|prostat\w*)\b", re.I),
    "female": re.compile(r"\b(females?|women|woman|pregnan\w*|antenatal|lactat\w*|menopaus\w*|post menopausal)\b", re.I),
    "child": re.compile(r"\b(child\w*|paediatric|pediatric|infants?|neonat\w*|newborns?|<\s*\d+\s*(yrs?|years))\b", re.I),
    "adult": re.compile(r"\b(adults?|older\s*>\s*\d+)\b", re.I),
}
_DOSE_IN_TEXT = re.compile(r"\d\s*(mg|mcg|g|ml|iu|units?|%)\b|\b(od|bd|tds|tid|qid)\b", re.I)


def _who(age: int, gender: str) -> str:
    if age < 1:
        return "infant"
    if age < 12:
        return "child"
    if age < 18:
        return "adolescent"
    return f"{'woman' if (gender or '').lower().startswith('f') else 'man' if (gender or '').lower().startswith('m') else 'adult'}"


def pass1_question(session, symptom_groups: list[list[str]]) -> str:
    """Short enough for the Query Encoder (64 tokens): who, what, how long."""
    terms = [g[0] for g in symptom_groups if g] or [session.symptoms or ""]
    since = f" for {session.duration}" if getattr(session, "duration", "") else ""
    return f"{_who(session.age, session.gender)} with {', '.join(terms[:6])}{since}"


def pass1(retriever: Retriever | None, session, symptom_groups: list[list[str]],
          consider: list[str] | tuple[str, ...] = ()) -> Evidence:
    """`consider`: up to 3 conditions the symptom-understanding step names
    for looking up (the likely one and a dangerous one). Their own guideline
    pages join the candidates, judged against this patient's presentation;
    the panel is told that a passage does not make a condition likely."""
    if retriever is None:
        return Evidence(note="the guideline database is not configured")
    try:
        return retriever.search(pass1_question(session, symptom_groups), DIAGNOSIS, k=PASS1_K,
                                topics=list(consider)[:3])
    except Exception as e:  # noqa: BLE001 - a report never fails for want of evidence
        log.warning("Guideline search (pass 1) failed: %s", e)
        return Evidence(note="the guideline search failed")


def fits_patient(breadcrumb: str, session) -> bool:
    """False when a box's heading names only another patient group."""
    head = breadcrumb.rsplit(" › ", 1)[-1]
    female = (session.gender or "").lower().startswith("f")
    male = (session.gender or "").lower().startswith("m")
    child = session.age < 12
    named = {g for g, rx in _GROUP_WORDS.items() if rx.search(head)}
    if named & {"male", "female"} and not named & ({"female"} if female else {"male"} if male else {"male", "female"}):
        return False
    if named & {"child", "adult"} and not named & ({"child"} if child else {"adult"}):
        return False
    return True


def _page_boxes(retriever, best, session, have: set[int]) -> list:
    """Treatment boxes from the same guideline page as a condition's best
    passage, for this patient's group: "Cystitis in females (nitrofurantoin
    100 mg BD x 5d)" when the search found "Male UTI" on that page."""
    if best is None or best.page is None or best.tier > 2 or not hasattr(retriever, "page_boxes"):
        return []
    try:
        boxes = retriever.page_boxes(best)
    except Exception as e:  # noqa: BLE001
        log.warning("Page look-up failed: %s", e)
        return []
    out = [b for b in boxes if b.id not in have and fits_patient(b.breadcrumb, session) and _DOSE_IN_TEXT.search(b.body)]
    return out[:PAGE_BOXES]


def pass2(retriever: Retriever | None, session, conditions: list[dict]) -> Evidence:
    if retriever is None:
        return Evidence(note="the guideline database is not configured")
    who = _who(session.age, session.gender)
    names = [c["name"] for c in conditions if c.get("name")][:3]
    if not names:
        return Evidence(note="no condition to look up")
    merged = Evidence(query=" / ".join(names))
    seen: set[int] = set()
    for name in names:
        try:
            ev = retriever.search(f"{name} treatment and dose for {who}", TREATMENT, k=PASS2_PER_CONDITION,
                                  topic_hint=name, rerank_n=PASS2_RERANK)
        except Exception as e:  # noqa: BLE001
            log.warning("Guideline search (pass 2) failed for %s: %s", name, e)
            continue
        found = [p for p in ev.passages if fits_patient(p.breadcrumb, session)]
        # the page of the best guideline hit, even when that box is for another group
        best = next((p for p in ev.passages if p.page is not None and p.tier <= 2), None)
        for p in found + _page_boxes(retriever, best, session, seen | {p.id for p in ev.passages}):
            if p.id not in seen and len(merged.passages) < PASS2_MAX:
                seen.add(p.id)
                p.pass_name = "treatment"
                merged.passages.append(p)
    if not merged.passages:
        merged.note = "no treatment passage found"
    return merged


def printed_doses(retriever: Retriever | None, session, conditions: list[dict]) -> tuple[str, list[dict]]:
    """Doses printed FOR the concluded conditions (STW pages, NFI indications),
    as a block for the writer and as rows for the dose check."""
    if retriever is None:
        return "", []
    child = session.age < 12
    rows: list[dict] = []
    lines: list[str] = []
    for c in [c for c in conditions if c.get("name")][:3]:
        try:
            found = retriever.condition_doses(c["name"], limit=PRINTED_PER_CONDITION * 2)
        except Exception as e:  # noqa: BLE001
            log.warning("Printed-dose look-up failed for %s: %s", c["name"], e)
            continue
        # this patient's age group first; the other group's rows are not shown
        found = [d for d in found if d["population"] in ("any", "child" if child else "adult", *(["neonate"] if session.age < 1 else []))]
        for d in found[:PRINTED_PER_CONDITION]:
            rows.append(d)
            how = " ".join(x for x in (d["dose"], d["route"], d["frequency"], d["duration"]) if x)
            where = d["source"] + (f", page {d['page']}" if d.get("page") else "")
            lines.append(f"- {c['name']}: {d['drug']}: {how} ({d['population']}; {where})")
    if not lines:
        return "", []
    head = ("Printed doses for the concluded conditions (as printed in the source; the indication text may "
            "list other uses too, so check that each fits THIS patient):")
    return head + "\n" + "\n".join(lines), rows


def number(first: Evidence, second: Evidence | None = None) -> list:
    """Labels [S1].. across both passes (pass 1 first)."""
    for p in first.passages:
        p.pass_name = p.pass_name or "diagnosis"
    return label(first, *([second] if second else []))


def brands_taken(retriever: Retriever | None, taken: str) -> str:
    """'Dolo 650, Pan D' -> a line saying what each brand contains, from the
    brand table (256k Indian and US brands). Empty when nothing is known."""
    if retriever is None or not (taken or "").strip():
        return ""
    found = []
    for item in [t.strip() for t in taken.replace(";", ",").split(",") if t.strip()][:6]:
        try:
            hit = retriever.brand(item)
        except Exception as e:  # noqa: BLE001
            log.warning("Brand look-up failed: %s", e)
            return ""
        if hit:
            parts = " + ".join(
                (str(c.get("drug", "")) + (" " + str(c["strength"]) if c.get("strength") else "")) for c in hit["composition"]
            )
            found.append(f"{item} = {parts}")
    if not found:
        return ""
    return "Medication already taken, from the brand list (check with the patient): " + "; ".join(found) + "."


def _lines_naming(drug: str, text: str) -> list[str]:
    """Lines of a passage that name the medicine and carry a dose."""
    from .drugnames import canonical
    from .text import words

    name_words = {w for w in words(drug) + canonical(drug).split() if len(w) > 3}
    out = []
    for line in text.split("\n"):
        lw = set(words(line)) | set(canonical(line).split())
        if name_words & lw and _DOSE_IN_TEXT.search(line):
            out.append(line.strip(" -*|"))
    return out


def dose_conflicts(medicines: list[dict], evidence: Evidence, printed: list[dict] | None = None) -> str:
    """For the pharmacist review, written by code: each drafted medicine
    whose dose is NOT in the guideline lines that name it, with those lines.
    (The writer once gave ciprofloxacin the 100 mg printed for nitrofurantoin.)"""
    notes = []
    for i, m in enumerate(medicines, 1):
        name, dose = m.get("name", ""), m.get("dose", "")
        if not name or not dose:
            continue
        texts = [f"{p.breadcrumb}\n{p.body}" for p in evidence.passages]
        texts += [f"{d['drug']} {d['dose']} {d['frequency']} {d['duration']}" for d in printed or []]
        if dose_found(dose, name, texts):
            continue
        quoted = []
        for p in evidence.passages:
            quoted += [f"[{p.label}] {ln}" for ln in _lines_naming(name, p.body)]
        for d in printed or []:
            if _lines_naming(name, d["drug"] + " 1 mg"):
                quoted.append(f"(printed, {d['source']}) {d['drug']} {d['dose']} {d['frequency']} {d['duration']}".strip())
        if quoted:
            shown = "; ".join(q[:160] for q in quoted[:3])
            notes.append(f"Medicine {i} ({name} {dose}): this dose is not in the guideline lines that name it: {shown}")
    if not notes:
        return ""
    return ("GUIDELINE DOSE CHECK (by code, before your review):\n" + "\n".join(notes) +
            "\nFor each one: approve only if the written dose is still a standard adult dose for THIS patient "
            "and condition (the quoted line may be for another group); a dose taken from another medicine's "
            "line must be rejected.")


def check_doses(retriever: Retriever | None, medicines: list[dict], evidence: Evidence,
                printed: list[dict] | None = None) -> list[dict]:
    """Adds `doseEvidence` to each medicine: whether its dose numbers were
    found in a guideline passage, a printed dose for the concluded
    conditions, or a printed dose for that medicine."""
    out = []
    for m in medicines:
        name, dose = m.get("name", ""), m.get("dose", "")
        found, where = False, ""
        for p in evidence.passages:
            if dose_found(dose, name, [f"{p.breadcrumb}\n{p.body}"]):
                found, where = True, f"[{p.label}] {p.source_title}" + (f", page {p.page}" if p.page else "")
                break
        candidates: list[dict] = list(printed or [])
        if retriever is not None and not found:
            try:
                candidates += retriever.doses(name)
            except Exception as e:  # noqa: BLE001
                log.warning("Dose look-up failed for %s: %s", name, e)
        if not found:
            for d in candidates:
                if dose_found(dose, name, [f"{d['drug']} {d['dose']} {d['frequency']} {d['duration']}"]):
                    found, where = True, f"{d['source']}" + (f", page {d['page']}" if d.get("page") else "")
                    break
        out.append({**m, "doseEvidence": {"found": found, "source": where} if dose else {"found": False, "source": ""}})
    return out
