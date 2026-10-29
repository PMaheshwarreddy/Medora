"""The languages a patient can use at the kiosk, in one place.

The patient's report (screen and PDF) is given in ONE language: the one the
patient used (the user's rule of 2026-10-28). English is always prepared too,
because the checks in patient_view.py compare against it, but it is shown
only to English speakers.

To add a language: an entry here (its name, and the letters its script uses,
so patient_view can tell a translation from English), its labels in
report_pdf.py (`_L` and the small tables beside it) and a font for its script
there, its strings class in frontend/lib/l10n/strings.dart, and its code in
the `language` fields of schemas.py and handoff/router.py.
"""

import re

LANGUAGES: dict[str, dict] = {
    "en": {"name": "English", "script": None},
    "ml": {"name": "Malayalam", "script": re.compile(r"[ഀ-ൿ]")},
}


def supported(code: str | None) -> str:
    """The language code to use: the visit's, or English if it is unknown."""
    return code if code in LANGUAGES else "en"


def name(code: str) -> str:
    return LANGUAGES[supported(code)]["name"]


def in_script(code: str, text: str) -> bool:
    """Whether the text contains letters of that language's own script."""
    script = LANGUAGES[supported(code)]["script"]
    return bool(script and script.search(text or ""))


def any_local_script(text: str) -> bool:
    """Whether the text contains letters of any non-Latin kiosk language."""
    return any(lang["script"] and lang["script"].search(text or "") for lang in LANGUAGES.values())
