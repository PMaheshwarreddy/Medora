"""The patient's report, in the patient's own language.

The report the pipeline writes is clinical English: it is what the safety
reviews and rules check, and what the doctor reads. The patient reads
`patientView`, built here from that checked report and the visit:

  patient details, what they told us (symptoms, since when, medicines
  taken, allergies), vitals, a short summary, possible conditions (a plain
  name and one sentence about each, with the AI's estimate as a percentage:
  the user's choice of 2026-10-29, replacing likelihood words only), medicines (name,
  form and strength, how to take it, what it is for, caution), precautions
  and lifestyle advice.

Every text is given as {"en": simple English, "<code>": the visit's
language}: English is always prepared (the checks below compare against
it), the visit's language only when it is not English. The screen and PDF
show ONE language, the visit's (`view["language"]`; the user's rule of
2026-10-28, replacing the manager's two-language report of 2026-10-22).
Languages are listed in languages.py. One Gemini call rewrites the
patient-facing texts in plain words and translates them; it may not add or
drop information. Guards in code:

- How to take a medicine is assembled here from the reviewed dose,
  frequency, duration and daily maximum; the model only translates it.
- Every number in a source text must appear in what comes back, or the
  source English is kept and the translation dropped for that item.
- A sensitive word (sensitive.py) the source did not have is removed.
- A wrong item count drops the whole rewrite.

Without Gemini (offline, or a failure) the view is the report's own English
(`translated: false`), and the kiosk says so in the patient's language.
"""

import logging
import re

from . import languages, sensitive
from .llm import Llm, LlmError

log = logging.getLogger("medora.patient_view")

_PROMPT = """You prepare the patient's copy of a hospital pre-consultation \
report. Each input item has a task. Return ONE JSON object:
{{"items": [{{"en": "..."{local_key}}}, ...]}} with exactly one entry per input
item, in the same order.

Tasks:
- simplify: rewrite the English in plain, friendly words a patient with
  little schooling understands, speaking to the patient as "you"; short
  sentences{then_local}.
- translate: keep the English exactly as given in "en"{translate_local}.
- patient_words: the patient's own words. "en" must be in ENGLISH letters
  (translate them into English if they are in another language){words_local}.
  Faithful: do not add, interpret or drop anything.
- condition_name: the everyday name of this condition in "en" (the same name
  if it is already plain){name_local} Never a broader word (influenza is not
  just "fever").
- condition_about: one plain sentence saying what this condition is, in
  general terms{about_local}. No advice, no medicines, no promises.

Rules for every item:{local_rule}
- Keep medicine names, numbers and units (mg, ml, %, bpm, mmHg, °C) exactly
  as written, in English letters.
- Keep the meaning: add nothing, leave nothing out, do not soften or
  strengthen a warning, never add a diagnosis or a medicine."""


def _prompt(code: str) -> str:
    if code == "en":
        return _PROMPT.format(local_key="", then_local="", translate_local="", words_local="",
                              name_local=".", about_local="", local_rule="")
    lang = languages.name(code)
    return _PROMPT.format(
        local_key=f', "{code}": "..."',
        then_local=f'; then give the same in {lang} in "{code}"',
        translate_local=f'; give it in {lang} in "{code}"',
        words_local=f'; "{code}" in {lang}, in its own script',
        name_local=(f'; in "{code}" the specific name {lang} speakers use for THIS condition, or '
                    f'if there is none, the English name written in {lang} script.'),
        about_local=f', in "en" and "{code}"',
        local_rule=f"\n- {lang}: simple, polite, everyday {lang} in its own script.",
    )

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> list[str]:
    return sorted(_NUMBER.findall(text or ""))


def _pair(en: str | None, local: str | None = None, code: str = "en") -> dict | None:
    en = (en or "").strip()
    if not en:
        return None
    out = {"en": en}
    if code != "en":
        out[code] = (local or "").strip() or None
    return out


def how_to_take(m: dict) -> str:
    """The dose instruction, from the reviewed fields only."""
    parts = [m.get("dose") or ""]
    if m.get("frequency"):
        parts.append(m["frequency"])
    text = ", ".join(p for p in parts if p)
    duration = (m.get("duration") or "").strip()
    if duration:
        # "3 days" reads "for 3 days"; "until the fever settles" stands alone.
        starts = duration.lower().split()[0]
        text += f", {duration}" if starts in ("until", "till", "as", "when", "while", "for") else f", for {duration}"
    text = text[:1].upper() + text[1:] + "." if text else ""
    if m.get("maxDaily"):
        text += f" At most {m['maxDaily']} in 24 hours."
    return text.strip()


# Answers that mean "nothing to report", in English and Malayalam.
_NOTHING = {"none", "no", "nil", "nothing", "na", "n/a", "not applicable", "no allergies",
            "no known allergies", "nkda", "none taken", "no medicine", "no medicines",
            "ഇല്ല", "ഒന്നുമില്ല", "അലർജി ഇല്ല", "അലർജിയില്ല"}


def _said(text: str | None) -> str:
    """The patient's answer, or "" when it only says there is nothing."""
    value = (text or "").strip()
    return "" if value.lower().strip(" .") in _NOTHING else value


def _items(report: dict, session) -> list[tuple[tuple, str, str]]:
    """(where it goes, task, source text) for every patient-facing text."""
    out: list[tuple[tuple, str, str]] = []

    def add(path: tuple, task: str, text) -> None:
        if isinstance(text, str) and text.strip():
            out.append((path, task, text.strip()))

    add(("summary",), "simplify", report.get("clinicalSummary") or report.get("summary"))
    add(("symptoms",), "patient_words", session.symptoms)
    add(("duration",), "patient_words", session.duration)
    # A "none" answer is not shown as a line of its own (the user's rule of
    # 2026-10-29: no "none" on the report); a known allergy always is.
    add(("medicationsTaken",), "patient_words", _said(session.medications))
    add(("allergies",), "patient_words", _said(getattr(session, "allergies", "") or ""))
    for i, c in enumerate(report.get("possibleConditions") or []):
        add(("conditions", i, "name"), "condition_name", c.get("name"))
        add(("conditions", i, "about"), "condition_about", c.get("name"))
    for i, m in enumerate(report.get("medicines") or []):
        add(("medicines", i, "howToTake"), "translate", how_to_take(m))
        add(("medicines", i, "purpose"), "simplify", m.get("purpose"))
        add(("medicines", i, "caution"), "simplify", m.get("caution"))
    for i, v in enumerate(report.get("vitalsAssessment") or []):
        add(("vitals", i, "note"), "simplify", v.get("note"))
    for i, line in enumerate(report.get("vitalFlags") or []):
        add(("vitalFlags", i), "simplify", line)
    for i, line in enumerate(report.get("precautions") or []):
        add(("precautions", i), "simplify", line)
    for i, line in enumerate(report.get("lifestyleAdvice") or []):
        add(("lifestyle", i), "simplify", line)
    # Only in a doctor's final report.
    for i, line in enumerate(report.get("testsAdvised") or []):
        add(("tests", i), "simplify", line)
    add(("followUp",), "simplify", report.get("followUp"))
    add(("medicinesNote",), "simplify", report.get("medicinesNote"))
    add(("note",), "simplify", report.get("panelNote"))
    return out


def _percents(report: dict) -> list[int | None]:
    """Each listed condition's percentage, the same number the doctor sees
    (doctorView), else worked out the same way (triage.with_probabilities)."""
    from .triage import with_probabilities

    listed = report.get("possibleConditions") or []
    if report.get("doctorDiagnosis"):
        return [None] * len(listed)  # the signed report: the doctor's diagnosis
    doctor = {
        str(c.get("name", "")).lower(): c.get("probability")
        for c in (report.get("doctorView") or {}).get("conditions") or []
    }
    own = with_probabilities(listed)
    out = []
    for c, mine in zip(listed, own):
        pct = doctor.get(str(c.get("name", "")).lower())
        out.append(int(pct) if isinstance(pct, (int, float)) else mine.get("probability"))
    return out


def _skeleton(report: dict, session) -> dict:
    """The view's shape, with the structured parts filled in and every text
    still empty."""
    return {
        "patient": {
            "name": session.name,
            "age": session.age,
            "gender": session.gender,
            "phone": session.phone,
        },
        "summary": None,
        "symptoms": None,
        "duration": None,
        "medicationsTaken": None,
        "allergies": None,
        "conditions": [
            {"name": None, "about": None, "likelihood": c.get("likelihood", "low"), "probability": pct}
            for c, pct in zip(report.get("possibleConditions") or [], _percents(report))
        ],
        "medicines": [
            {
                "name": m.get("name", ""),
                "form": m.get("form", ""),
                "strength": m.get("strength", ""),
                "prescription": bool(m.get("prescription")),
                # given by the doctor or nurse (injections, emergency care)
                "doctorOnly": bool(m.get("doctorOnly")),
                "howToTake": None,
                "purpose": None,
                "caution": None,
            }
            for m in report.get("medicines") or []
        ],
        "vitals": [
            {k: v.get(k) for k in ("name", "value", "normal", "status")} | {"note": None}
            for v in report.get("vitalsAssessment") or []
        ],
        "vitalFlags": [None] * len(report.get("vitalFlags") or []),
        "precautions": [None] * len(report.get("precautions") or []),
        "lifestyle": [None] * len(report.get("lifestyleAdvice") or []),
        "tests": [None] * len(report.get("testsAdvised") or []),
        "followUp": None,
        "medicinesNote": None,
        "note": None,
        # the language shown, and whether the texts are in it
        "language": languages.supported(getattr(session, "language", None)),
        "translated": False,
        "bilingual": False,  # older readers: same as translated
    }


def _put(view: dict, path: tuple, value) -> None:
    target = view
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _clean(view: dict) -> dict:
    """Drops the list entries no text was found for."""
    for key in ("vitalFlags", "precautions", "lifestyle", "tests"):
        view[key] = [x for x in view[key] if x]
    view["conditions"] = [c for c in view["conditions"] if c["name"]]
    return view


def plain_view(report: dict, session) -> dict:
    """The view without a model: the report's own English, untranslated."""
    view = _skeleton(report, session)
    for path, task, text in _items(report, session):
        if task == "condition_about":
            continue  # nothing to say without the model
        _put(view, path, _pair(text))
    # an English visit needs no translation
    view["translated"] = view["bilingual"] = view["language"] == "en"
    return _clean(view)


def _check(task: str, source: str, en: str, local: str, code: str) -> tuple[str, str | None]:
    """What may be shown for one item: the model's text where it keeps the
    source's numbers and adds no sensitive word, the source otherwise.
    `local` is the text in the visit's language (empty for English)."""
    local = local if code != "en" else ""
    if task in ("condition_name", "condition_about"):
        # Made from a name: nothing numeric to keep, nothing to add.
        if (sensitive.mentions(en) or sensitive.mentions(local)) and not sensitive.mentions(source):
            return (source if task == "condition_name" else ""), None
        return en or (source if task == "condition_name" else ""), local or None
    wanted = _numbers(source)
    if task == "translate":
        en = source  # kept exactly; only the translation is new
    if task == "patient_words" and en and languages.any_local_script(en):
        en = source if not languages.any_local_script(source) else ""
    if task == "simplify":
        # Plain words may leave a number out, never add or change one.
        if not en or not set(_numbers(en)) <= set(wanted):
            en = source
        if local and set(_numbers(local)) != set(_numbers(en)):
            local = ""
    else:
        if task != "patient_words" and (not en or _numbers(en) != wanted):
            en = source
        if local and _numbers(local) != wanted:
            local = ""
    if local and not languages.in_script(code, local) and task != "translate":
        local = ""  # not actually in the patient's language
    if not en:
        # Words the model would not put into English: shown as they are.
        en, local = (local or source), ""
    if sensitive.mentions(en) and not sensitive.mentions(source):
        en = sensitive.strip_sentences(en) or source
    if local and sensitive.mentions(local) and not sensitive.mentions(source):
        local = ""
    return en, local or None


async def build_patient_view(llm: Llm | None, report: dict, session) -> dict:
    """The patient's report in their language. Never raises: without the
    model it falls back to `plain_view`."""
    items = _items(report, session)
    code = languages.supported(getattr(session, "language", None))
    usable = llm is not None and getattr(llm, "clinical", False) and not str(getattr(llm, "name", "")).startswith("ollama")
    if not usable or not items:
        return plain_view(report, session)
    try:
        raw = await llm.json(
            _prompt(code),
            "Items:\n" + "\n".join(f"{i}. [{task}] {text}" for i, (_, task, text) in enumerate(items, 1)),
            thinking=0,
        )
    except LlmError as e:
        log.warning("Could not prepare the patient's wording: %s", e)
        return plain_view(report, session)
    if str(getattr(llm, "name", "")).startswith("ollama"):
        return plain_view(report, session)  # Gemini failed over to the small model
    answers = raw.get("items")
    if not isinstance(answers, list) or len(answers) != len(items):
        log.warning("Patient wording returned %s items for %d", len(answers) if isinstance(answers, list) else "no", len(items))
        return plain_view(report, session)

    view = _skeleton(report, session)
    for (path, task, source), answer in zip(items, answers):
        answer = answer if isinstance(answer, dict) else {}
        en, local = _check(task, source, str(answer.get("en") or "").strip(),
                           str(answer.get(code) or "").strip() if code != "en" else "", code)
        _put(view, path, _pair(en, local, code))
    view["translated"] = view["bilingual"] = True
    return _clean(view)
