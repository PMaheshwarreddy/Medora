"""Words the kiosk report never shows unless the patient raised them.

A kiosk report is read by the patient, often with family beside them. The
user decided on 2026-10-18 that pregnancy and sexual-health conditions and
advice must never appear in it on the AI's initiative ("it should not even
ever suggest those kind of words"). Clinically, though, a woman of
child-bearing age with lower abdominal pain must have a pregnancy test
before imaging or most medicines, and missing an ectopic pregnancy can
kill. So the report keeps that step for the doctor in neutral clinical
wording (LMP, urine hCG), and drops every line that names the topic.
If the patient mentioned it themselves, nothing is hidden.
"""

import re

_SENSITIVE = re.compile(
    r"pregnan|ectopic|miscarri|abortion|gestation|antenatal|trimester|"
    r"conception|contracept|condom|sexual|sexually|intercourse|"
    r"\bstis?\b|\bstds?\b|venereal|gonorrh|chlamydia|syphilis|trichomon|"
    r"genital herpes|\bhiv\b|\baids\b|\bhpv\b|pelvic inflammatory|\bpid\b|vaginal|vagina|"
    # The same in Malayalam, for a patient's own words and translated text.
    r"ഗർഭ|ഗര്ഭ|ഗർഭിണി|ഗർഭച്ഛിദ്ര|ഗർഭം അലസ|ഗർഭനിരോധ|ലൈംഗിക|കോണ്ടം|എച്ച്.?ഐ.?വി|യോനി",
    re.I,
)

# What the doctor reads instead, for a woman of child-bearing age.
DOCTOR_CHECK = "Check the date of the last menstrual period and a urine hCG test before imaging or medicines."


def raised_by_patient(*texts: str) -> bool:
    return any(_SENSITIVE.search(t or "") for t in texts)


def mentions(text: str) -> bool:
    return bool(_SENSITIVE.search(text or ""))


def strip_sentences(text: str) -> str:
    """The text without the sentences that name the topic."""
    return _sentences(text)


def _sentences(text: str) -> str:
    """The text without the sentences that name the topic."""
    parts = re.split(r"(?<=[.!?।])\s+", text or "")
    return " ".join(p for p in parts if not mentions(p)).strip()


def clean(report: dict, symptoms: str, medications: str, could_conceive: bool, pregnancy: str = "") -> dict:
    """The report with sensitive conditions, advice and wording removed,
    unless the patient raised the topic, or answered yes or unsure when the
    voice agent asked whether she could be pregnant. Changes `report` in
    place."""
    if raised_by_patient(symptoms, medications) or pregnancy in ("yes", "unsure"):
        return report
    hidden = [c for c in report.get("possibleConditions", []) if mentions(c.get("name", ""))]
    report["possibleConditions"] = [c for c in report.get("possibleConditions", []) if c not in hidden]
    report["conditionsRuledOut"] = [c for c in report.get("conditionsRuledOut") or [] if not mentions(c)]
    for key in ("precautions", "lifestyleAdvice", "doctorNotes"):
        report[key] = [line for line in report.get(key) or [] if not mentions(line)]
    for key in ("summary", "clinicalSummary"):
        report[key] = _sentences(report.get(key, ""))
    for m in report.get("medicines", []):
        for key in ("caution", "purpose", "forCondition"):
            m[key] = _sentences(m.get(key, ""))
    if hidden or (could_conceive and report.get("possibleConditions") is not None and _abdominal(report, symptoms)):
        if DOCTOR_CHECK not in report["doctorNotes"]:
            report["doctorNotes"] = [DOCTOR_CHECK, *report["doctorNotes"]][:6]
    # Kept out of the stored panel record too: it is part of the report.
    for o in report.get("panel", []):
        o["assessment"] = _sentences(o.get("assessment", ""))
    report["discussion"] = _sentences(report.get("discussion", ""))
    return report


def _abdominal(report: dict, symptoms: str) -> bool:
    text = " ".join([symptoms, *(c.get("name", "") for c in report.get("possibleConditions", []))]).lower()
    return any(w in text for w in ("lower abdom", "lower stomach", "lower belly", "pelvi", "period", "menstru", "bleeding", "ovar"))
