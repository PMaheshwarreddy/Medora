"""The last step of a report: a writer drafts it in full, including medicines
with doses, a separate reviewer checks it, and rules in code have the final
word. Nothing a model writes reaches the report unchecked.

  1. Writer: from the case, the vitals assessment, the knowledge-base
     evidence and the specialist panel's conclusion, it writes the clinical
     summary and the medicines (with dose, frequency, duration and cautions),
     and fills what the panel left out (lifestyle advice, points for the
     doctor). Without a panel it also names the possible conditions.
  2. Reviewer: an independent pass, told to act as a cautious clinical
     pharmacist. It approves or rejects each medicine and checks that the
     summary claims nothing the case does not show. It can only remove,
     never add or reword.
  3. Code: no medicines for children under 12 (doses depend on weight) or for
     an emergency; no controlled drugs; a dose must look like a dose;
     prescription medicines are marked; a woman who could be pregnant gets a
     pregnancy check on every medicine. If the reviewer cannot be reached,
     no written medicine is shown.

Medicines are suggestions for the treating doctor, never instructions for
the patient, and the report says so.
"""

import logging
import re

from .ingest.transform import normalize
from .llm import Llm, LlmError, clinical

log = logging.getLogger("medora.report_writer")

MAX_MEDICINES = 5

_WRITER = """You are a senior physician writing the pre-consultation report a \
hospital doctor reads before seeing a patient. Your medicines are suggestions \
for that doctor to confirm, never instructions to the patient. Patient safety \
comes first: when unsure, leave a medicine out. Use only facts in the case. \
Return ONE JSON object:
{
  "clinical_summary": "3-5 sentences for the doctor: who the patient is, what they report and since when, the relevant vital signs, and the panel's assessment",
  "possible_conditions": [{"name": "...", "likelihood": "low" | "medium" | "high", "reasoning": "one sentence"}],
  "medicines": [{
    "name": "generic name",
    "for_condition": "which listed condition or symptom it treats",
    "form": "tablet | capsule | syrup | suspension | drops | inhaler | cream | gel | ointment | sachet | lozenge | spray",
    "strength": "strength of one unit, e.g. 500 mg tablet, 125 mg/5 ml syrup",
    "dose": "amount per dose, e.g. 500 mg (1 tablet), 5 ml",
    "frequency": "e.g. every 6 hours as needed",
    "duration": "e.g. 3 days, or until the fever settles",
    "route": "oral | inhaled | topical | ...",
    "max_daily": "maximum in 24 hours, or empty when not applicable",
    "purpose": "what it does here, in plain words",
    "caution": "the main caution for THIS patient, or empty",
    "prescription": true or false,
    "evidence": "the label of the guideline passage this medicine and dose follow, e.g. S3, or empty"
  }],
  "lifestyle_advice": ["up to 4 short points in plain words, no medicine names"],
  "doctor_notes": ["up to 5 short points the doctor should check or ask"]
}

possible_conditions: {conditions_rule}

medicines: up to {most}. Treat THIS case, not only its fever:
- Work through the likely conditions and the main complaints one by one and
  give each the medicine a doctor would usually start at a first visit. A
  report whose only medicine is paracetamol is right only when fever or pain
  is the whole problem.
- First choice: the "Guideline passages on treatment and doses" in the case.
  When a passage gives the first-line medicine and dose for a listed
  condition and this age group, use that medicine and dose as printed, and
  put the passage label in "evidence". Indian sources (tier 1) come first.
  A workflow often has one box per patient group ("Cystitis in females",
  "Male UTI", children): use the box for THIS patient's sex and age. Copy a
  dose only from the line that names that same medicine; never give one
  medicine the dose printed beside another.
- Otherwise standard first-line treatment as in the National List of
  Essential Medicines, the WHO Model List and national standard treatment
  guidelines, with the usual adult dose from standard references. Generic
  names only, no brands, as they are written in India (paracetamol, not
  acetaminophen; salbutamol, not albuterol). A US label passage (tier 3) is
  for safety details; take the medicine choice and dose from an Indian
  source when the case has one.
- "Printed doses for the concluded conditions" lists doses an Indian source
  prints for that condition: prefer one that fits this patient, copying its
  dose, frequency and duration.
- Prefer medicines from the "Medicines in the knowledge base" list when they
  fit, copying the name exactly.
- Paracetamol only when fever or pain is reported.
- Symptomatic treatment (fever, pain, cough, nausea) is fine for a likely
  self-limiting illness. Antibiotics, antivirals and steroids only when a
  listed condition clearly needs one; mark those prescription true.
- A condition that must be confirmed by a test before it is treated (malaria,
  dengue, typhoid, tuberculosis, and any infection whose treatment depends on
  the organism) gets symptomatic treatment only; its specific treatment
  waits for the result, so say which test in doctor_notes instead.
- Never: opioids, sedatives or other controlled drugs.
- Injections only when standard first-line care for this case calls for one
  (route "injection"); they are for the doctor to decide, never the patient.
- A child under 12: only when the weight is given, with a weight-based dose
  (mg per kg, and the dose that gives for this weight); otherwise none.
- When the urgency is "emergency": only what an emergency team would
  typically start first, for the doctor.
- Never suggest a medicine the patient reports an allergy to, or one from
  the same family (a penicillin allergy rules out amoxicillin; an allergy to
  a painkiller rules out the other NSAIDs).
- Check every medicine against the patient's age, sex, vital signs and the
  medication they have already taken: do not repeat one they already take
  without saying so in caution, and respect its maximum daily dose.
- For a woman aged 12-50, consider pregnancy in caution.
- A long-term medicine the patient has run out of (metformin for known type
  2 diabetes, an antihypertensive): suggest restarting it at the usual
  starting dose, and say in caution that the doctor sets the dose to the
  patient's previous regimen and checks the sugar or blood pressure first.
- "Medication already taken" is often an Indian brand name: work out the
  generic (Dolo, Crocin, Calpol = paracetamol; Combiflam = ibuprofen +
  paracetamol; Brufen = ibuprofen; Meftal = mefenamic acid; Cetzine, Okacet
  = cetirizine; Allegra = fexofenadine; Pan, Pantocid = pantoprazole;
  Digene, Gelusil = antacid; Electral = ORS). If it is the right medicine,
  suggest it again with the correct interval and daily maximum, and say in
  caution that the doses already taken count towards that maximum.
- For a routine or soon case, the patient should leave with the treatment a
  doctor in an Indian outpatient clinic would usually give at a first visit.
  Common first-line choices for adults (a guideline passage in the case comes
  first):
  fever or body pain: paracetamol, usually 650 mg for an adult (500 mg to
  1 g; at most 4 g in 24 hours);
  influenza-like illness that is severe, needs admission or is in a
  high-risk patient (over 65, pregnancy, diabetes, heart or lung disease):
  oseltamivir 75 mg twice daily for 5 days, whatever the duration;
  common cold, allergic rhinitis, sneezing, itchy eyes: a non-drowsy
  antihistamine, cetirizine, levocetirizine or fexofenadine (not
  chlorpheniramine for daytime symptoms), with paracetamol for a cold with
  fever; allergic rhinitis lasting weeks: add fluticasone nasal spray;
  hives or itching: cetirizine;
  dry cough: dextromethorphan;
  heartburn, acidity, dyspepsia: pantoprazole before breakfast, or an antacid;
  nausea or vomiting: ondansetron or domperidone; loose stools: ORS (zinc for
  children); constipation: isabgol (psyllium) or lactulose;
  burning urination in a woman who cannot be pregnant (uncomplicated
  cystitis): nitrofurantoin;
  ringworm or other fungal skin infection: clotrimazole cream;
  scabies: permethrin 5% cream; head lice: permethrin 1% lotion;
  muscle or joint strain, low back pain: topical diclofenac gel, or ibuprofen
  if nothing in the case argues against an NSAID;
  migraine or tension headache: paracetamol or ibuprofen;
  wheeze in a known asthmatic: salbutamol inhaler;
  worms: albendazole single dose;
  sore throat: warm saline gargles in advice, paracetamol; an antibiotic
  (amoxicillin) only with features of a bacterial throat infection
  (fever, pus on tonsils, tender neck glands, no cough).
- If no medicine is clearly right, return an empty list.

lifestyle_advice and doctor_notes: start from the panel's lists below, keep
what is right, and add what is missing (for example a vital sign that was
not measured and should be). Plain, specific, short."""

_FIT = """You check the possible conditions in a pre-consultation report \
against what the patient actually reported. Conditions come from a symptom \
search and a panel of AI specialists; some share only one common symptom \
with the case and do not fit it. Return ONE JSON object:
{
  "conditions": [{"number": 1, "keep": true or false,
                  "pointed_to_by": "the reported symptom, duration or vital sign that points to THIS condition",
                  "reason": "one sentence for the doctor: why it does or does not fit this patient"}]
}
For each condition, in order:
1. The first, most likely condition: keep it if the patient's account fits it.
2. Every other condition: find what in the case points to it MORE than to the
   most likely condition. A symptom both share (fever, body pain, tiredness,
   cough) does not count. Keep it only if you can name such a feature, or if
   a specific red-flag feature of this case makes it necessary to rule out
   (for example pneumonia for cough with low oxygen; appendicitis for pain
   that moved to the right lower abdomen).
   A must-rule-out with nothing pointing to it beyond a common symptom
   is false: the doctor's routine checks cover it.
3. Otherwise keep is false. Example: for "fever and body pains for two days"
   with normal vitals, hepatitis (needs jaundice, dark urine or right upper
   abdominal pain) and tuberculosis (needs weeks of cough, weight loss, night
   sweats) are false.
pointed_to_by must quote or closely paraphrase the case; leave it empty when
keep is false."""

_REVIEW = """You are a cautious clinical pharmacist and patient-safety \
reviewer. Another model wrote the draft below for a hospital doctor. You may \
only approve or reject; you never add or reword. Return ONE JSON object:
{
  "medicines": [{"number": 1, "approve": true or false, "reason": "short"}],
  "summary_ok": true or false,
  "summary_problem": "what is wrong with the summary, or empty"
}
Reject a medicine if ANY of these is true:
- the dose, frequency, duration or maximum daily amount is not a standard
  adult one, is missing where it matters, or is wrong for the route;
- it does not treat a listed condition or a reported symptom;
- it is unsafe or contraindicated for this patient as far as the case shows
  (age, sex, vital signs, urgency, medication already taken);
- it duplicates or interacts with medication already taken and the caution
  does not say so (continuing a medicine the patient already took is right
  when the caution says those doses count towards the daily maximum);
- the patient reports an allergy to it or to its family;
- it is an antibiotic, antiviral or steroid without a clear indication in
  the case, or it is a controlled drug or an injection;
- for a woman who could be pregnant, it is clearly harmful in pregnancy
  (for example an ACE inhibitor, a statin, isotretinoin, a tetracycline)
  and the caution does not say so. For every woman aged 12-50 the code adds
  "Doctor to check LMP / hCG before giving" to each medicine not known to be
  safe in pregnancy, so a missing pregnancy caution is not by itself a
  reason to reject.
- A long-term medicine the patient has run out of (metformin for known
  diabetes, an antihypertensive) may be restarted at its usual starting
  dose when the caution says the doctor will set the dose to their previous
  regimen: approve that.
An antiviral for influenza (oseltamivir) is NOT to be rejected for being
past 48 hours of illness when the case is severe, urgent or an emergency,
or the patient is high-risk (over 65, pregnancy, diabetes, heart or lung
disease): treatment is then given whatever the duration.
The patient is in India: the usual Indian tablet strengths and doses are
standard. Paracetamol 650 mg every 6 to 8 hours (at most 4 g in 24 hours)
is the commonest adult dose in India (Dolo 650, Calpol 650): approve it;
500 mg and 1 g are standard too.
A dose that matches a guideline passage [S1].. quoted in the case (as the
medicine's "evidence" says) is a standard dose for that passage's patients.
summary_ok is false if the summary states anything the case does not contain.
When in doubt, reject."""

# Never suggested from a kiosk, whatever a model says.
_CONTROLLED = re.compile(
    r"\b(morphine|codeine|tramadol|tapentadol|oxycodone|hydrocodone|fentanyl|pethidine|"
    r"buprenorphine|methadone|diazepam|lorazepam|alprazolam|clonazepam|midazolam|"
    r"nitrazepam|zolpidem|ketamine|phenobarbital|methylphenidate|amphetamine)\b",
    re.I,
)
_PRESCRIPTION = re.compile(
    r"(cillin|mycin|micin|floxacin|cycline|cef|sulfamethoxazole|trimethoprim|nitrofurantoin|"
    r"metronidazole|tinidazole|linezolid|vancomycin|oseltamivir|acyclovir|valacyclovir|"
    r"prednis|dexamethasone|hydrocortisone tablet|methylprednisolone|warfarin|insulin)",
    re.I,
)
# Standard first-line choices in pregnancy: no LMP / hCG check is noted.
_SAFE_IN_PREGNANCY = re.compile(
    r"paracetamol|acetaminophen|oral rehydration|\bors\b|zinc|antacid|calcium carbonate|"
    r"simethicone|saline|lactulose|isabgol|psyllium",
    re.I,
)
_DOSE = re.compile(r"(\d+(\.\d+)?|\b(one|two|three|half|a)\b)\s*(mg|mcg|µg|g|grams?|gm|ml|mL|millilitres?|iu|IU|units?|puffs?|drops?|tablets?|capsules?|%|sachets?)\b", re.I)
_TOPICAL = re.compile(r"\b(topical|skin|cream|gel|ointment|lotion|local)\b", re.I)
_STRENGTH = re.compile(r"\d+(\.\d+)?\s*(%|mg|mcg|g\b|ml|iu)", re.I)
_APPLY = re.compile(r"\b(apply|applied|thin layer|fingertip|massage|rub|smear)\b", re.I)


def _usable_dose(m: dict) -> bool:
    """A dose with an amount; for a skin preparation, how to apply it with
    its strength (permethrin 5% cream: "apply a thin layer from the neck down")."""
    dose = _text(m.get("dose"), 80)
    if _DOSE.search(dose):
        return True
    where = f"{_text(m.get('route'), 30)} {_text(m.get('form'), 30)}"
    return bool(_TOPICAL.search(where) and _APPLY.search(dose) and _STRENGTH.search(_text(m.get("strength"), 80)))


def _text(value, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _list(value, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:limit]


def _medicines_raw(raw) -> list[dict]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and _text(item.get("name")):
            out.append(item)
    return out[: MAX_MEDICINES + 3]


def drafted_medicines(draft_: dict) -> list[dict]:
    """The draft's medicines as the review numbers them."""
    return _medicines_raw(draft_.get("medicines"))


def _numbered_medicines(medicines: list[dict]) -> str:
    if not medicines:
        return "(none)"
    return "\n".join(
        f"{i}. {m.get('name')} ({m.get('form') or 'form not given'}, {m.get('strength') or 'strength not given'}): "
        f"{m.get('dose')} {m.get('route', '')}, {m.get('frequency')}, "
        f"for {m.get('duration')}; max in 24 h: {m.get('max_daily') or 'n/a'}; "
        f"for {m.get('for_condition')}; caution: {m.get('caution') or 'none'}; "
        f"prescription: {m.get('prescription')}"
        + (f"; follows guideline passage [{m.get('evidence')}]" if m.get("evidence") else "")
        for i, m in enumerate(medicines, 1)
    )


def _approved(review: dict, key: str, count: int) -> set[int]:
    approved = set()
    for item in review.get(key) if isinstance(review.get(key), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if 1 <= number <= count and item.get("approve") is True:
            approved.add(number)
    return approved


def _review_reasons(review: dict, count: int) -> dict[int, str]:
    out = {}
    for item in review.get("medicines") if isinstance(review.get("medicines"), list) else []:
        if isinstance(item, dict):
            try:
                n = int(item.get("number"))
            except (TypeError, ValueError):
                continue
            if 1 <= n <= count:
                out[n] = _text(item.get("reason"), 300)
    return out


def _rule_reason(m: dict, allergies: str) -> str:
    name = _text(m.get("name"), 80)
    if _CONTROLLED.search(name):
        return "controlled drug"
    if _allergic(name, allergies):
        return "the patient reports an allergy to it or its family"
    if not _usable_dose(m) or not _text(m.get("frequency"), 80):
        return "no usable dose or frequency"
    return "a rule in code (age, weight or the medicine limit)"


# The forms the local model fills in for the check and the review (Ollama
# structured output). MedGemma in plain JSON mode once wrote on until its
# time ran out, and once broke the JSON: the review was lost both times.
def _form(item: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": item, "required": required}


_TEXT = {"type": "string", "maxLength": 240}
FIT_FORM = _form({"conditions": {"type": "array", "maxItems": 8, "items": _form(
    {"number": {"type": "integer"}, "keep": {"type": "boolean"}, "pointed_to_by": _TEXT, "reason": _TEXT},
    ["number", "keep", "pointed_to_by", "reason"])}}, ["conditions"])
REVIEW_FORM = _form({
    "medicines": {"type": "array", "maxItems": 10, "items": _form(
        {"number": {"type": "integer"}, "approve": {"type": "boolean"}, "reason": _TEXT},
        ["number", "approve", "reason"])},
    "summary_ok": {"type": "boolean"}, "summary_problem": _TEXT,
}, ["medicines", "summary_ok", "summary_problem"])  # fmt: skip


def _kept(fit: dict, count: int) -> set[int]:
    """Conditions the check kept, each with a reason from the case."""
    kept = set()
    for item in fit.get("conditions") if isinstance(fit.get("conditions"), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if 1 <= number <= count and item.get("keep") is True and _text(item.get("pointed_to_by")):
            kept.add(number)
    return kept


def _local(llm: Llm) -> bool:
    """A small general model answered: not trusted with medicines."""
    return not clinical(llm)


# Indian brand names patients type for "medication already taken".
_BRANDS = {
    "dolo": "paracetamol", "crocin": "paracetamol", "calpol": "paracetamol",
    "pacimol": "paracetamol", "sumo": "paracetamol nimesulide",
    "combiflam": "ibuprofen paracetamol", "brufen": "ibuprofen", "meftal": "mefenamic",
    "cetzine": "cetirizine", "okacet": "cetirizine", "allegra": "fexofenadine",
    "pan": "pantoprazole", "pantocid": "pantoprazole", "omez": "omeprazole",
    "rantac": "ranitidine", "electral": "ors", "volini": "diclofenac", "moov": "diclofenac",
}  # fmt: skip


# The same, as patients write them in Malayalam (normalize() drops
# Malayalam letters, so these are matched on the original text).
_MALAYALAM_NAMES = {
    "ഡോളോ": "paracetamol", "ക്രോസിൻ": "paracetamol", "കാൽപോൾ": "paracetamol",
    "പാരസെറ്റമോൾ": "paracetamol", "പാരാസെറ്റമോൾ": "paracetamol",
    "കോമ്പിഫ്ലാം": "ibuprofen paracetamol", "ഐബുപ്രോഫെൻ": "ibuprofen",
    "സെട്രിസിൻ": "cetirizine", "സെറ്റിറിസിൻ": "cetirizine", "പാന്റോപ്രസോൾ": "pantoprazole",
}  # fmt: skip


def _generics(taken: str) -> str:
    """What the patient took, with brand names spelled out as generics."""
    words = normalize(taken).split()
    malayalam = [generic for name, generic in _MALAYALAM_NAMES.items() if name in (taken or "")]
    return " ".join([*words, *(_BRANDS[w] for w in words if w in _BRANDS), *malayalam])


# Allergy words and the medicines they rule out: an allergy names a family
# as often as a drug.
_ALLERGY_FAMILIES = [
    (re.compile(r"penicillin|amoxi|ampicillin|cillin", re.I), re.compile(r"cillin|amoxiclav|co-amoxiclav", re.I)),
    (re.compile(r"sulfa|sulpha|sulfonamide", re.I), re.compile(r"sulfa|sulpha|trimethoprim", re.I)),
    (re.compile(r"cephalo|cef", re.I), re.compile(r"\bcef|ceph", re.I)),
    (
        re.compile(r"aspirin|nsaid|ibuprofen|diclofenac|painkiller|pain killer|brufen|combiflam", re.I),
        re.compile(r"aspirin|ibuprofen|diclofenac|naproxen|mefenamic|ketorolac|aceclofenac|nimesulide|etoricoxib", re.I),
    ),
    (re.compile(r"paracetamol|acetaminophen|dolo|crocin|calpol", re.I), re.compile(r"paracetamol|acetaminophen", re.I)),
    (re.compile(r"macrolide|azithro|erythro|clarithro", re.I), re.compile(r"mycin\b|azithro|erythro|clarithro", re.I)),
    (re.compile(r"quinolone|cipro|levoflox|oflox", re.I), re.compile(r"floxacin", re.I)),
]


# Dosage forms a kiosk report may name. Injections are never suggested here
# (the rules drop them); the doctor portal will handle those.
_FORMS = (
    "tablet", "capsule", "syrup", "suspension", "drops", "inhaler", "cream", "gel",
    "ointment", "sachet", "lozenge", "spray", "solution",
)  # fmt: skip


def _form(value, route: str) -> str:
    """The dosage form as one of `_FORMS`, or a guess from the route."""
    text = _text(value, 40).lower()
    for form in _FORMS:
        if form in text:
            return form
    route = route.lower()
    if "inhal" in route:
        return "inhaler"
    if "topical" in route:
        return "cream"
    return "tablet" if not text else text.split()[0]


def _allergic(medicine: str, allergies: str) -> bool:
    """Whether the patient reported an allergy to this medicine or its
    family. "none" and the like name nothing."""
    text = " ".join([allergies or "", _generics(allergies)])
    if not text.strip():
        return False
    name = medicine.lower()
    first = normalize(name.split()[0]) if name.split() else ""
    if first and len(first) >= 4 and first in normalize(text).split():
        return True
    return any(said.search(text) and drug.search(name) for said, drug in _ALLERGY_FAMILIES)


def _could_be_pregnant(age: int, gender: str) -> bool:
    return gender == "female" and 12 <= age <= 50


def _material(case, vitals_line, urgency, conditions, panel, known_medicines) -> str:
    panel_text = (
        "No specialist panel reviewed this case."
        if panel is None
        else "Specialist panel conclusion:\n"
        f"Summary: {panel.get('summary', '')}\n"
        f"Discussion: {panel.get('discussion', '')}\n"
        f"Lifestyle advice: {panel.get('lifestyle_advice', [])}\n"
        f"Points for the doctor: {panel.get('doctor_notes', [])}"
    )
    listed = (
        "\n".join(f"- {c['name']} ({c['likelihood']}): {c.get('reasoning', '')}" for c in conditions)
        or "- none named"
    )
    known = "\n".join(f"- {name}: {uses or 'no details'}" for name, uses in known_medicines.items()) or "- none"
    return (
        f"{case}\n\n{vitals_line}\nUrgency decided: {urgency}\n\n"
        f"Possible conditions:\n{listed}\n\n{panel_text}\n\n"
        f"Medicines in the knowledge base for these conditions:\n{known}"
    )


async def draft(
    llm: Llm,
    case: str,
    vitals_line: str,
    urgency: str,
    conditions: list[dict],
    panel: dict | None,
    known_medicines: dict[str, str],
) -> dict:
    """The writer's draft. `panel` is the chair's conclusion, or None when
    the panel did not run, in which case the draft names conditions too.
    `known_medicines` maps knowledge-base medicines linked to the listed
    conditions to what they are used for."""
    rule = (
        "copy the conditions listed above exactly, in the same order; do not add or remove any."
        if panel is not None
        else "at most 4, most likely first, each supported by something in the case; "
        "common illnesses before rare ones. Return an empty list if the case is too vague."
    )
    result = await llm.json(
        _WRITER.replace("{conditions_rule}", rule).replace("{most}", str(MAX_MEDICINES)),
        _material(case, vitals_line, urgency, conditions, panel, known_medicines),
        thinking=1024,
    )
    if _local(llm):
        raise LlmError("Only the hosted model may write medicines and conditions")
    return result


def written_conditions(draft_: dict) -> list[dict]:
    """Conditions a draft named (only when there was no panel)."""
    return [
        {
            "name": _text(c.get("name"), 120),
            "likelihood": _text(c.get("likelihood"), 10).lower() or "low",
            "reasoning": _text(c.get("reasoning"), 400),
        }
        for c in (draft_.get("possible_conditions") or [])
        if isinstance(c, dict) and _text(c.get("name"))
    ][:4]


async def check_conditions(llm: Llm, case: str, vitals_line: str, conditions: list[dict]) -> set[str] | None:
    """Its own focused pass: which conditions fit what the patient said.
    The names kept, or None when the check could not be made."""
    if not conditions:
        return set()
    try:
        fit = await llm.json(
            _FIT,
            f"{case}\n\n{vitals_line}\n\nPossible conditions, most likely first:\n"
            + "\n".join(
                f"{i}. {c.get('name')} ({c.get('likelihood')}): {c.get('reasoning', '')}"
                for i, c in enumerate(conditions, 1)
            ),
            thinking=512,
            answer_tokens=600,
            schema=FIT_FORM,
        )
    except LlmError as e:
        log.warning("The condition check failed: %s", e)
        return None
    if _local(llm):
        return None
    kept = _kept(fit, len(conditions))
    if kept and 1 not in kept:
        # The panel's most likely condition is never dropped while a less
        # likely one stays: that would make a "low" must-rule-out the
        # headline (uncontrolled diabetes dropped, DKA kept, 2026-10-29).
        # Its doubt still reaches the doctor below.
        kept = {1, *kept}
        doubted_first = True
    else:
        doubted_first = False
    result = Kept(c["name"] for i, c in enumerate(conditions, 1) if i in kept)
    # Why each dropped one was doubted, for the doctor (who sees them all).
    for item in fit.get("conditions") if isinstance(fit.get("conditions"), list) else []:
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 1 <= number <= len(conditions) and number not in kept:
            result.reasons[conditions[number - 1]["name"]] = _text(item.get("reason"), 300)
        elif number == 1 and doubted_first:
            log.info("The condition check doubted the most likely condition (kept): %s", _text(item.get("reason"), 200))
    return result


class Kept(set):
    """The condition names a check kept, with `reasons` for the others."""

    def __init__(self, names=()):
        super().__init__(names)
        self.reasons: dict[str, str] = {}


async def finish(
    llm: Llm,
    draft_: dict,
    case: str,
    vitals_line: str,
    urgency: str,
    age: int,
    gender: str,
    conditions: list[dict],
    panel: dict | None,
    known_medicines: dict[str, str],
    taken: str = "",
    allergies: str = "",
    pregnancy: str = "",
    weight_kg: float | None = None,
    dose_notes: str = "",
) -> dict:
    """The independent review of a draft, then the rules in code. Without
    the review, nothing written is shown. `conditions` are the ones that
    stand after the condition check."""
    medicines = _medicines_raw(draft_.get("medicines"))
    try:
        review = await llm.json(
            _REVIEW,
            f"{_material(case, vitals_line, urgency, conditions, panel, known_medicines)}\n\nDRAFT\n"
            f"Summary: {draft_.get('clinical_summary', '')}\n\n"
            f"Medicines:\n{_numbered_medicines(medicines)}" + (f"\n\n{dose_notes}" if dose_notes else ""),
            thinking=1024,
            answer_tokens=700,
            schema=REVIEW_FORM,
        )
        reviewed = not _local(llm)
    except LlmError as e:
        log.warning("Report review failed, written medicines are withheld: %s", e)
        review, reviewed = {}, False

    approved = _approved(review, "medicines", len(medicines))
    kept = [m for i, m in enumerate(medicines, 1) if i in approved]
    summary = _text(draft_.get("clinical_summary"), 1500) if reviewed and review.get("summary_ok") is True else ""
    final, note = _rules(kept, urgency, age, gender, known_medicines, reviewed, taken, allergies, pregnancy, weight_kg)
    for_doctor = doctor_medicines(kept, urgency, age, gender, known_medicines, reviewed, taken, allergies, pregnancy, weight_kg)
    # Every refusal, with who refused it and why, for the doctor (and for
    # tuning the writer: a refusal is either a writer error or a reviewer
    # that is too strict).
    reasons = _review_reasons(review, len(medicines))
    allowed = {normalize(m["name"]) for m in for_doctor}
    rejected = []
    for i, m in enumerate(medicines, 1):
        line = {"name": _text(m.get("name"), 80), "dose": _text(m.get("dose"), 80), "frequency": _text(m.get("frequency"), 80)}
        if i not in approved:
            rejected.append({**line, "by": "review" if reviewed else "no review",
                             "reason": reasons.get(i, "") or ("the safety review could not be reached" if not reviewed else "")})
        elif normalize(line["name"][:1].upper() + line["name"][1:]) not in allowed:
            rejected.append({**line, "by": "rules", "reason": _rule_reason(m, allergies)})
    log.info("Report writer: %d of %d medicines approved", len(final), len(medicines))
    return {
        "clinicalSummary": summary,
        "medicines": final,
        "doctorMedicines": for_doctor,
        "medicinesNote": note,
        "medicinesReviewed": len(medicines),
        "medicinesRejected": rejected,
        "lifestyleAdvice": _list(draft_.get("lifestyle_advice"), 4),
        "doctorNotes": _list(draft_.get("doctor_notes"), 5),
    }


def label(medicines: list[dict], known: dict[str, str]) -> list[dict]:
    """Marks each medicine as from the knowledge base (with its stored name)
    or suggested, against the knowledge-base medicines of the listed
    conditions."""
    keys = {normalize(n): n for n in known}
    out = []
    for m in medicines:
        key = normalize(m["name"])
        out.append(
            {**m, "name": keys.get(key, m["name"]), "source": "knowledge_base" if key in keys else "suggested"}
        )
    return out


def _rules(
    medicines: list[dict],
    urgency: str,
    age: int,
    gender: str,
    known: dict[str, str],
    reviewed: bool,
    taken: str = "",
    allergies: str = "",
    pregnancy: str = "",
    weight_kg: float | None = None,
) -> tuple[list[dict], str]:
    """The rules no model can override. Returns the medicines a patient may
    see and, when there are none, why. `doctor_medicines` gives the wider
    list only a doctor sees."""
    patient, _ = _checked(medicines, urgency, age, gender, known, reviewed, taken, allergies, pregnancy, weight_kg)
    if age < 12:
        return [], "Medicine doses for children depend on their weight, so the doctor will decide them."
    if urgency == "emergency":
        return [], "This needs immediate care; the doctor will decide any treatment."
    if not reviewed:
        return [], "Medicines could not be checked by the safety review, so none are suggested."
    return patient, "" if patient else "No medicine is suggested for this case; the doctor will decide."


def doctor_medicines(
    medicines: list[dict],
    urgency: str,
    age: int,
    gender: str,
    known: dict[str, str],
    reviewed: bool,
    taken: str = "",
    allergies: str = "",
    pregnancy: str = "",
    weight_kg: float | None = None,
) -> list[dict]:
    """Every reviewed medicine a doctor may consider: those a patient may
    see, plus injections, weight-based children's doses and emergency
    treatment, each marked `doctorOnly`. Controlled drugs, allergies and
    malformed doses are still refused. Nothing without the review."""
    if not reviewed:
        return []
    _, everything = _checked(medicines, urgency, age, gender, known, reviewed, taken, allergies, pregnancy, weight_kg)
    return everything


def _checked(
    medicines, urgency, age, gender, known, reviewed, taken, allergies, pregnancy, weight_kg
) -> tuple[list[dict], list[dict]]:
    """(for the patient, for the doctor) after the rules in code."""
    patient: list[dict] = []
    doctor: list[dict] = []
    for m in medicines:
        name = _text(m.get("name"), 80)
        name = name[:1].upper() + name[1:]
        dose = _text(m.get("dose"), 80)
        frequency = _text(m.get("frequency"), 80)
        route = _text(m.get("route"), 30) or "oral"
        if _CONTROLLED.search(name):
            continue
        if _allergic(name, allergies):
            continue
        if not _usable_dose(m) or not frequency:
            continue
        injection = "inject" in route.lower() or route.lower() in ("im", "iv", "sc", "intramuscular", "intravenous")
        child = age < 12
        if child and not weight_kg:
            continue  # no weight, no child's dose
        caution = _text(m.get("caution"), 240)
        # Medication the patient already took counts towards the same limit.
        if name and normalize(name.split()[0]) in _generics(taken) and "already" not in caution.lower():
            caution = (caution + " " if caution else "") + (
                "The patient has already taken this: count those doses towards the daily maximum."
            )
        if pregnancy in ("yes", "unsure") and not _SAFE_IN_PREGNANCY.search(name):
            # She was asked and said she may be: the doctor must confirm.
            caution = (caution + " " if caution else "") + (
                "She says she may be pregnant: confirm this is safe in pregnancy."
            )
        elif _could_be_pregnant(age, gender) and "hcg" not in caution.lower() and not _SAFE_IN_PREGNANCY.search(name):
            # Neutral wording: the report is read by the patient (sensitive.py).
            caution = (caution + " " if caution else "") + "Doctor to check LMP / hCG before giving."
        item = {
            "name": name,
            "forCondition": _text(m.get("for_condition"), 120),
            "form": "injection" if injection else _form(m.get("form"), route),
            "strength": _text(m.get("strength"), 80),
            "dose": dose,
            "frequency": frequency,
            "duration": _text(m.get("duration"), 80),
            "route": route,
            "maxDaily": _text(m.get("max_daily"), 80),
            "purpose": _text(m.get("purpose"), 200),
            "caution": caution,
            "prescription": bool(m.get("prescription")) or bool(_PRESCRIPTION.search(name)) or injection,
            "doctorOnly": injection or child or urgency == "emergency",
            # The guideline passage [S..] the writer says this follows ("" if none).
            "evidence": _text(m.get("evidence"), 8).strip("[] "),
        }
        if len(doctor) < MAX_MEDICINES + 2:
            doctor.append(item)
        if not item["doctorOnly"] and len(patient) < MAX_MEDICINES:
            patient.append({k: v for k, v in item.items() if k != "doctorOnly"})
    # Named in the knowledge base for a listed condition, or written by the
    # report AI and approved by the reviewer.
    return label(patient, known), label(doctor, known)
