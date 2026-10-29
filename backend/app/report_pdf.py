import base64
import io
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import IntakeSession
from .patient_view import plain_view

# Medora's colours (frontend MedoraColors): pine, terracotta, warm greys.
_PINE = colors.HexColor("#1D4D3B")
_ACCENT = colors.HexColor("#C8573A")
_MUTED = colors.HexColor("#6E685E")
_BORDER = colors.HexColor("#E4DACB")
_SAGE = colors.HexColor("#3F8A68")
# Fixed labels: one entry per language, in the order of _ORDER (same wording
# as the kiosk's lib/l10n/strings.dart). A new language adds its text to
# each entry and its code to _ORDER (see languages.py).
_ORDER = ("en", "ml")
_L = {
    "title": ("Medora pre-consultation report", "മെഡോറ പരിശോധനാ റിപ്പോർട്ട്"),
    "urgency": ("Urgency", "അടിയന്തരാവസ്ഥ"),
    "department": ("Department", "വിഭാഗം"),
    "patient": ("Patient", "രോഗി"),
    "name": ("Name", "പേര്"),
    "age": ("Age / gender", "വയസ്സ് / ലിംഗം"),
    "phone": ("Phone", "ഫോൺ"),
    "told": ("What you told us", "നിങ്ങൾ പറഞ്ഞത്"),
    "symptoms": ("Symptoms", "ബുദ്ധിമുട്ടുകൾ"),
    "since": ("Since when", "എപ്പോൾ മുതൽ"),
    "taken": ("Medicines already taken", "ഇതിനകം കഴിച്ച മരുന്നുകൾ"),
    "allergies": ("Allergies", "അലർജി"),
    "vitals": ("Your vitals", "നിങ്ങളുടെ പരിശോധനാ ഫലം"),
    "normal_range": ("normal", "സാധാരണ"),
    "summary": ("Summary", "സംഗ്രഹം"),
    "conditions": ("Possible conditions", "സാധ്യമായ രോഗാവസ്ഥകൾ"),
    "not_diagnosis": (
        "For your doctor to confirm. This is not a diagnosis.",
        "ഡോക്ടർ ഉറപ്പാക്കേണ്ടവ. ഇത് രോഗനിർണ്ണയമല്ല.",
    ),
    "medicines": ("Medications the doctor may consider", "ഡോക്ടർ പരിഗണിച്ചേക്കാവുന്ന മരുന്നുകൾ"),
    "medicines_note": (
        "The doctor decides on these. Do not take, stop or change any medicine until your doctor tells you.",
        "ഇവ ഡോക്ടറാണ് തീരുമാനിക്കുക. ഡോക്ടർ പറയുന്നതുവരെ ഒരു മരുന്നും കഴിക്കുകയോ നിർത്തുകയോ മാറ്റുകയോ ചെയ്യരുത്.",
    ),
    "how": ("How to take", "എങ്ങനെ കഴിക്കണം"),
    "for": ("What it is for", "എന്തിന്"),
    "caution": ("Caution", "ശ്രദ്ധിക്കുക"),
    "prescription": ("Needs a doctor's prescription", "ഡോക്ടറുടെ കുറിപ്പടി വേണം"),
    "doctor_gives": (
        "Only the doctor or nurse gives this. Do not take it yourself.",
        "ഇത് ഡോക്ടറോ നഴ്സോ മാത്രമേ നൽകൂ. സ്വയം എടുക്കരുത്.",
    ),
    "precautions": ("While you wait", "കാത്തിരിക്കുമ്പോൾ"),
    "lifestyle": ("Lifestyle advice", "ജീവിതശൈലി നിർദ്ദേശങ്ങൾ"),
    "disclaimer": (
        "This is an automated summary for your doctor to confirm. It is not a diagnosis or a prescription.",
        "ഇത് ഡോക്ടർ ഉറപ്പാക്കേണ്ട ഒരു സ്വയംപ്രവർത്തിത സംഗ്രഹമാണ്. ഇത് രോഗനിർണ്ണയമോ കുറിപ്പടിയോ അല്ല.",
    ),
    "english_only": (
        "The Malayalam version could not be prepared for this report.",
        "ഈ റിപ്പോർട്ടിന്റെ മലയാളം പതിപ്പ് തയ്യാറാക്കാൻ കഴിഞ്ഞില്ല.",
    ),
}
_URGENCY = {
    "routine": ("Routine", "സാധാരണ പരിശോധന"),
    "soon": ("See a doctor soon", "വേഗം ഡോക്ടറെ കാണുക"),
    "urgent": ("Urgent", "അടിയന്തരമായി കാണണം"),
    "emergency": ("Emergency: tell the staff now", "അത്യാഹിതം: ഉടൻ ജീവനക്കാരെ അറിയിക്കുക"),
}
_STATUS = {"normal": ("Normal", "സാധാരണം"), "low": ("Low", "കുറവ്"), "high": ("High", "കൂടുതൽ")}
_LIKELIHOOD = {"high": ("More likely", "കൂടുതൽ സാധ്യത"), "medium": ("Possible", "സാധ്യതയുണ്ട്")}
_GENDER = {"male": ("Male", "പുരുഷൻ"), "female": ("Female", "സ്ത്രീ")}
_FORM = {
    "tablet": "ഗുളിക", "capsule": "ക്യാപ്സ്യൂൾ", "syrup": "സിറപ്പ്", "suspension": "സിറപ്പ്",
    "drops": "തുള്ളി മരുന്ന്", "inhaler": "ഇൻഹേലർ", "cream": "ക്രീം", "gel": "ജെൽ",
    "ointment": "ഓയിന്റ്മെന്റ്", "sachet": "സാഷെ", "lozenge": "ലോസഞ്ച്", "spray": "സ്പ്രേ",
}  # fmt: skip
_VITAL = {
    "Heart rate": "ഹൃദയമിടിപ്പ്",
    "Oxygen (SpO2)": "ഓക്സിജൻ നില (SpO2)",
    "Temperature": "ശരീര താപനില",
    "Blood pressure": "രക്തസമ്മർദ്ദം",
}


def _say(entry, code: str) -> str:
    """One text in the report's language: a label tuple (in _ORDER) or a
    patient-view text {"en": ..., "<code>": ...}; English when the
    language's text is missing."""
    if not entry:
        return ""
    if isinstance(entry, dict):
        return (entry.get(code) or entry.get("en") or "").strip()
    i = _ORDER.index(code) if code in _ORDER else 0
    value = entry[i] if i < len(entry) else ""
    return (value or entry[0] or "").strip()


def _report_language(view: dict, report: dict) -> str:
    code = view.get("language") or report.get("language") or "en"
    return code if code in _ORDER else "en"



# Malayalam needs its own font, and shaping (uharfbuzz) to join its letters;
# Noto Sans Malayalam has no Latin letters, so each run of Malayalam is set in
# it and everything else in Public Sans (a TrueType font, which shaping needs).
_FONTS = Path(__file__).parent / "fonts"
_MALAYALAM = re.compile(r"[\u0D00-\u0D7F]")
_RUNS = re.compile(r"[\u0D00-\u0D7F\u200C\u200D]+|[^\u0D00-\u0D7F\u200C\u200D]+")
_malayalam_chars: set[int] = set()
_registered = False


def _register_fonts() -> None:
    global _registered
    if _registered:
        return
    for name, file in (
        ("Sans", "PublicSans-400.ttf"), ("Sans-Bold", "PublicSans-700.ttf"),
        ("Malayalam", "NotoSansMalayalam-Regular.ttf"), ("Malayalam-Bold", "NotoSansMalayalam-Bold.ttf"),
    ):  # fmt: skip
        font = TTFont(name, str(_FONTS / file))
        pdfmetrics.registerFont(font)
        if name == "Malayalam":
            _malayalam_chars.update(font.face.charToGlyph)
    for family, bold in (("Sans", "Sans-Bold"), ("Malayalam", "Malayalam-Bold")):
        addMapping(family, 0, 0, family)
        addMapping(family, 1, 0, bold)
        addMapping(family, 0, 1, family)
        addMapping(family, 1, 1, bold)
    _registered = True


def _markup(text: str, bold: bool = False) -> str:
    """Escaped text with every word that contains Malayalam set in the
    Malayalam font. Whole words, punctuation included: ReportLab shapes a
    word as one piece, and a word split across two fonts breaks the PDF."""
    face = "Malayalam-Bold" if bold else "Malayalam"
    out = []
    for token in re.split(r"(\s+)", text):
        if not _MALAYALAM.search(token):
            out.append(escape(token))
        elif all(ord(c) in _malayalam_chars for c in token):
            out.append(f'<font name="{face}">{escape(token)}</font>')
        else:
            # Malayalam joined to English letters ("Doloയും"): the parts,
            # each in its own font, with a space between them.
            out.append(" ".join(
                f'<font name="{face}">{escape(run)}</font>' if _MALAYALAM.search(run) else escape(run)
                for run in _RUNS.findall(token)
            ))  # fmt: skip
    return "".join(out)


def render_pdf(session: IntakeSession, report: dict) -> bytes:
    """The patient's report in the patient's language (patient_view.py), and
    a last page for the doctor in clinical English when no doctor reviews
    the report in the doctor portal."""
    _register_fonts()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Sans", fontSize=10.5, leading=15, shaping=1)
    local = ParagraphStyle("local", parent=body, fontSize=10, leading=15, textColor=_MUTED)
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontName="Sans-Bold", textColor=_PINE, fontSize=19, alignment=0, shaping=1)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Sans-Bold", textColor=_PINE, fontSize=12.5, spaceBefore=12, shaping=1)
    h3 = ParagraphStyle("h3", parent=body, fontName="Sans-Bold", fontSize=11, leading=15)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, textColor=_MUTED, leading=12)
    warn = ParagraphStyle("warn", parent=body, textColor=_ACCENT)

    strong = ParagraphStyle("strong", parent=body, fontName="Sans-Bold")

    def p(text: str, style=body, prefix: str = "") -> Paragraph:
        """`prefix` is markup (a bullet), not text."""
        return Paragraph(prefix + _markup(text, bold=style.fontName.endswith("Bold")), style)

    view = report.get("patientView") or plain_view(report, session)
    code = _report_language(view, report)

    def both(pair, style=body, prefix: str = "") -> list:
        """The text in the report's language (the name is historical: it
        once gave English with Malayalam beneath)."""
        text = _say(pair, code)
        return [p(text, style, prefix)] if text else []

    def title(key: str) -> list:
        return [p(_say(_L[key], code), h2)]

    def grid(rows: list[tuple[tuple[str, str], list]]) -> Table:
        """The label on the left, the content on the right."""
        table = Table(
            [[[p(_say(label, code), small)], content] for label, content in rows],
            colWidths=[44 * mm, 126 * mm],
        )
        table.setStyle(
            TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, _BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    info = view["patient"]
    gender = _GENDER.get(info.get("gender"), ("Other", "മറ്റുള്ളവർ"))
    department = report["department"]
    story = [
        p(_say(_L["title"], code), h1),
        p(session.created_at.strftime("%d %b %Y, %H:%M UTC") + f"  |  Visit number {session.id[:6].upper()}", small),
        Spacer(1, 8),
        grid(
            [
                (_L["urgency"], both(_URGENCY.get(report["urgency"], (report["urgency"], "")), h3)),
                (_L["department"], [p(department, h3)]),
            ]
        ),
        *title("patient"),
        # Empty details are left out rather than shown blank or as "None".
        grid(
            [
                (_L["name"], [p(info.get("name") or "")]),
                (_L["age"], [p(" / ".join(x for x in (
                    "" if info.get("age") is None else str(info["age"]),
                    _say(gender, code) if info.get("gender") else "",
                ) if x))]),
                *([(_L["phone"], [p(info["phone"])])] if info.get("phone") else []),
            ]
        ),
    ]
    told = [
        (_L["symptoms"], view.get("symptoms")),
        (_L["since"], view.get("duration")),
        (_L["taken"], view.get("medicationsTaken")),
        (_L["allergies"], view.get("allergies")),
    ]
    if any(pair for _, pair in told):
        story += [*title("told"), grid([(label, both(pair)) for label, pair in told if pair])]

    if view["vitals"]:
        rows = []
        for v in view["vitals"]:
            status = _STATUS.get(v.get("status"), ("Not judged", "വിലയിരുത്തിയില്ല"))
            content = [p(f"{v['value']}  ·  {_say(status, code)}", strong)]
            if v.get("normal"):
                content.append(p(f"{_say(_L['normal_range'], code)}: {v['normal']}", small))
            if v.get("note") and v.get("status") != "normal":
                content += both(v["note"], warn)
            rows.append(((v["name"], _VITAL.get(v["name"], "")), content))
        story += [*title("vitals"), grid(rows)]
    else:
        # Only without the rows above: they already say the same.
        for flag in view.get("vitalFlags") or []:
            story += both(flag, warn)

    if view.get("summary"):
        story += [*title("summary"), *both(view["summary"])]

    if view["conditions"]:
        story += [*title("conditions"), *both(_L["not_diagnosis"], small)]
        rows = []
        for c in view["conditions"]:
            chance = _LIKELIHOOD.get(c.get("likelihood"), ("Less likely", "സാധ്യത കുറവ്"))
            if c.get("probability") is not None:  # the AI's estimate, as the doctor sees it
                chance = tuple(f"{x} · {c['probability']}%" for x in chance)
            content = [*both(c["name"], strong), *both(c.get("about"), small)]
            rows.append((chance, content))
        story.append(grid(rows))

    if view["medicines"]:
        story += [*title("medicines"), *both(_L["medicines_note"], warn)]
        rows = []
        for m in view["medicines"]:
            form = m.get("form") or ""
            heading = " ".join(x for x in (m["name"], m.get("strength") or form) if x)
            content = [p(heading, strong)]
            if m.get("doctorOnly"):
                content += both(_L["doctor_gives"], warn)
            if m.get("howToTake"):
                content += [p(_say(_L["how"], code), small), *both(m["howToTake"])]
            if m.get("purpose"):
                content += [p(_say(_L["for"], code), small), *both(m["purpose"])]
            if m.get("caution"):
                content += [p(_say(_L["caution"], code), small), *both(m["caution"], warn)]
            if m.get("prescription"):
                content += both(_L["prescription"], small)
            rows.append(((form, _FORM.get(form, form)), content))
        story.append(grid(rows))
    elif view.get("medicinesNote"):
        story += [*title("medicines"), *both(view["medicinesNote"])]

    if view.get("precautions"):
        story += title("precautions")
        for line in view["precautions"]:
            story += both(line, prefix="&bull; ")
    if view.get("lifestyle"):
        story += title("lifestyle")
        for line in view["lifestyle"]:
            story += both(line, prefix="&bull; ")

    story += [Spacer(1, 14), *both(_L["disclaimer"], small)]
    if view.get("note"):
        story += both(view["note"], small)
    if code != "en" and not view.get("translated", view.get("bilingual")):
        story += both(_L["english_only"], small)

    if not report.get("awaitingDoctor"):
        # With doctor review the doctor works in the doctor portal, and the
        # patient's PDF never carries the AI's clinical suggestions.
        story += _doctor_page(report, p, h1, h2, small, grid)

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Medora pre-consultation report",
    ).build(story)
    return buffer.getvalue()


def _doctor_page(report: dict, p, h1, h2, small, grid) -> list:
    """For the doctor, in clinical English: what the safety-checked report
    says. Stands in for the doctor portal until it is built."""
    story = [PageBreak(), p("For the doctor (clinical)", h1)]
    if report.get("clinicalSummary") or report.get("summary"):
        story += [p("Clinical summary", h2), p(report.get("clinicalSummary") or report["summary"])]
    likelihood = {"high": "More likely", "medium": "Possible", "low": "Less likely"}
    if report.get("possibleConditions"):
        story += [
            p("Possible conditions", h2),
            grid(
                [
                    (
                        (likelihood.get(c["likelihood"], c["likelihood"]), ""),
                        [p(c["name"] + (f". {c['reasoning']}" if c.get("reasoning") else ""))],
                    )
                    for c in report["possibleConditions"]
                ]
            ),
        ]
    if report.get("conditionsRuledOut"):
        story += [p("Considered and ruled out", h2), p(", ".join(report["conditionsRuledOut"]))]
    if report.get("medicines"):
        rows = []
        for m in report["medicines"]:
            detail = "  ·  ".join(
                x for x in (
                    m.get("form"), m.get("strength"), m.get("dose"), m.get("route"), m.get("frequency"),
                    f"for {m['duration']}" if m.get("duration") else "",
                    f"max {m['maxDaily']}/24 h" if m.get("maxDaily") else "",
                ) if x
            )  # fmt: skip
            extra = [
                f"For {m['forCondition']}" if m.get("forCondition") else "",
                f"Caution: {m['caution']}" if m.get("caution") else "",
                "Prescription medicine" if m.get("prescription") else "",
            ]
            rows.append(((m["name"], ""), [p(detail), *[p(x, small) for x in extra if x]]))
        story += [p("Suggested medicines (for the doctor to confirm)", h2), grid(rows)]
    if report.get("doctorNotes"):
        story += [p("Points to check", h2), *[p(n, prefix="&bull; ") for n in report["doctorNotes"]]]
    return story


_FINAL = {
    "title": ("Consultation report and prescription", "പരിശോധനാ റിപ്പോർട്ടും കുറിപ്പടിയും"),
    "diagnosis": ("Diagnosis", "രോഗനിർണ്ണയം"),
    "rx": ("Medicines prescribed", "നിർദ്ദേശിച്ച മരുന്നുകൾ"),
    "none": ("No medicine was prescribed.", "മരുന്ന് നിർദ്ദേശിച്ചിട്ടില്ല."),
    "tests": ("Tests", "പരിശോധനകൾ"),
    "advice": ("Advice", "നിർദ്ദേശങ്ങൾ"),
    "follow": ("Follow-up", "തുടർ പരിശോധന"),
    "signed": ("Signed by", "ഒപ്പിട്ടത്"),
    "reg": ("Registration no.", "രജിസ്ട്രേഷൻ നമ്പർ"),
    "visit": ("Visit", "സന്ദർശനം"),
}


def render_final_pdf(session: IntakeSession, final: dict) -> bytes:
    """The doctor's signed report: hospital letterhead, the patient, the
    diagnosis, medicines with how to take them, tests, advice, follow-up and
    the doctor's name and registration number; in the patient's language."""
    from reportlab.platypus import Image

    _register_fonts()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("fbody", parent=styles["BodyText"], fontName="Sans", fontSize=10.5, leading=15, shaping=1)
    local = ParagraphStyle("flocal", parent=body, fontSize=10, textColor=_MUTED)
    strong = ParagraphStyle("fstrong", parent=body, fontName="Sans-Bold")
    head = ParagraphStyle("fhead", parent=body, fontName="Sans-Bold", fontSize=17, leading=21, textColor=_PINE)
    h2 = ParagraphStyle("fh2", parent=styles["Heading2"], fontName="Sans-Bold", textColor=_PINE, fontSize=12.5, spaceBefore=12, shaping=1)
    small = ParagraphStyle("fsmall", parent=body, fontSize=8.5, textColor=_MUTED, leading=12)

    def p(text: str, style=body, prefix: str = "") -> Paragraph:
        return Paragraph(prefix + _markup(text or "", bold=style.fontName.endswith("Bold")), style)

    hospital = final.get("hospital") or {}
    doctor = final.get("doctor") or {}
    view = final.get("view") or {}
    code = _report_language(view, final)

    def both(pair, style=body, prefix: str = "") -> list:
        text = _say(pair, code)
        return [p(text, style, prefix)] if text else []

    def say(key: str) -> str:
        return _say(_FINAL[key] if key in _FINAL else _L[key], code)

    def title(key: str) -> list:
        return [p(say(key), h2)]
    when = (final.get("finalizedAt") or "")[:16].replace("T", " ")

    # Letterhead: logo, name, contact line, the hospital's note.
    letter = [p(hospital.get("name") or "Hospital", head)]
    contact = "  ·  ".join(x for x in (hospital.get("address"), hospital.get("phone"), hospital.get("email")) if x)
    if contact:
        letter.append(p(contact, small))
    if hospital.get("note"):
        letter.append(p(hospital["note"], small))
    logo = hospital.get("logo") or ""
    if logo.startswith("data:image"):
        try:
            image = Image(io.BytesIO(base64.b64decode(logo.split(",", 1)[1])), width=20 * mm, height=20 * mm)
            header = Table([[image, letter]], colWidths=[24 * mm, 146 * mm])
        except Exception:
            header = Table([[letter]], colWidths=[170 * mm])
    else:
        header = Table([[letter]], colWidths=[170 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 1.2, _PINE), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))

    info = view.get("patient") or {}
    gender = _GENDER.get(info.get("gender"), ("Other", "മറ്റുള്ളവർ"))
    story = [
        header,
        Spacer(1, 8),
        p(say("title"), strong),
        p(f"{say('visit')}: {final.get('visitNumber', '')}  |  {when} UTC", small),
        Spacer(1, 6),
        p(f"{info.get('name', '')}  ·  {info.get('age', '')} / {_say(gender, code)}  ·  {info.get('phone', '')}", strong),
    ]
    if view.get("symptoms"):
        story += [p(say("symptoms"), small), *both(view["symptoms"])]
    if view.get("allergies"):
        story += [p(say("allergies"), small), *both(view["allergies"])]

    if view.get("conditions"):
        story += title("diagnosis")
        for c in view["conditions"]:
            story += both(c["name"], strong, "&bull; ")
            story += both(c.get("about"), small)

    story += title("rx")
    if view.get("medicines"):
        for i, m in enumerate(view["medicines"], 1):
            form = m.get("form") or ""
            heading = " ".join(x for x in (m["name"], m.get("strength") or "", form and f"({_say((form, _FORM.get(form, form)), code)})") if x)
            story.append(p(f"{i}. {heading}", strong))
            indent = ParagraphStyle("findent", parent=body, leftIndent=12)
            story += both(m.get("howToTake"), indent)
            story += both(m.get("caution"), ParagraphStyle("fwarn", parent=indent, textColor=_ACCENT))
    else:
        story += both(_FINAL["none"])

    if view.get("tests"):
        story += title("tests")
        for line in view["tests"]:
            story += both(line, prefix="&bull; ")
    if view.get("precautions"):
        story += title("advice")
        for line in view["precautions"]:
            story += both(line, prefix="&bull; ")
    if view.get("followUp"):
        story += [*title("follow"), *both(view["followUp"])]

    signature = [
        p(say("signed"), small),
        p(doctor.get("name", ""), strong),
        p(", ".join(x for x in (doctor.get("qualification"), doctor.get("department")) if x)),
        p(f"{say('reg')}: {doctor.get('registrationNumber', '')}"),
        p(f"{when} UTC", small),
    ]
    sign = Table([[signature]], colWidths=[80 * mm], hAlign="RIGHT")
    sign.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.6, _BORDER), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
    story += [Spacer(1, 20), sign]
    if code != "en" and not view.get("translated", view.get("bilingual")):
        story += [Spacer(1, 8), *both(_L["english_only"], small)]

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title="Consultation report",
    ).build(story)  # fmt: skip
    return buffer.getvalue()
