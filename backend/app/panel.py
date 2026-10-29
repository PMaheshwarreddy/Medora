"""The specialist panel: one CrewAI agent per medical specialty.

Instead of one model answering everything, the specialists a case concerns
read it and the knowledge-base evidence at the same time, each as their own
agent. A specialist who finds the case is outside their field steps aside
and takes no further part; the panel chair weighs the remaining opinions
against each other and writes the joint conclusion.

The patient's name, phone and email are never part of the case text.
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass

from .llm import CALL_TIMEOUT, with_retries

# CrewAI reports usage to its vendor unless told not to. Patient cases must
# not leave through that channel, so it is switched off before the import.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

log = logging.getLogger("medora.panel")

PEDIATRICS = "Pediatrics"
OBGYN = "Obstetrics & Gynecology"

# Departments a patient can be sent to that are not specialist agents: the
# general outpatient clinic for complaints no specialty owns (a viral fever,
# a cold), and the emergency department. The panel chair, a general
# physician, covers the general side; there is no generalist agent.
GENERAL_OPD = "General OPD"
EMERGENCY_DEPT = "Emergency Department"


@dataclass(frozen=True)
class Specialty:
    """What one specialist on the standard roster knows about their own job."""

    scope: str  # what belongs to them
    never_miss: str  # the dangerous conditions of their field
    not_theirs: str  # what they hand to a colleague


# The standard roster: specialists only. Every case is screened against all
# of these (`triage.understand`); only the ones the case concerns take part.
SPECIALISTS: dict[str, Specialty] = {
    PEDIATRICS: Specialty(
        "infants, children and teenagers: how illness presents, progresses and is dosed in the "
        "young, growth, feeding and development",
        "a febrile infant, dehydration, meningitis, breathing difficulty, a non-blanching rash, "
        "a child who is drowsy or floppy, intussusception, safeguarding concerns",
        "any patient aged 18 or over",
    ),
    "Cardiology": Specialty(
        "the heart and circulation: chest pain or pressure, palpitations, fainting, breathlessness "
        "on exertion or lying flat, ankle swelling, blood pressure problems",
        "heart attack and unstable angina, dangerous rhythm disturbances, heart failure, aortic "
        "dissection, pulmonary embolism, endocarditis",
        "chest pain that is clearly from the chest wall, the stomach or anxiety once the heart "
        "has been reasonably excluded",
    ),
    "Dermatology": Specialty(
        "the skin, hair and nails: rashes, itching, lumps, moles, ulcers, acne, hair loss, nail changes",
        "a widespread blistering or peeling rash, a rash with fever and illness, spreading skin "
        "infection, a changing or bleeding mole, a severe drug reaction",
        "symptoms with nothing to see or feel on the skin, hair or nails",
    ),
    "Gastroenterology": Specialty(
        "the gullet, stomach, bowel, liver, gallbladder and pancreas: abdominal pain, heartburn, "
        "nausea, vomiting, diarrhoea, constipation, jaundice, trouble swallowing",
        "bleeding from the gut (vomited blood, black or bloody stool), jaundice with fever, "
        "pancreatitis, liver failure, difficulty swallowing with weight loss",
        "abdominal pain that needs an operation (General Surgery), urinary or gynaecological causes",
    ),
    "Neurology": Specialty(
        "the brain, spinal cord and nerves: headache, dizziness, fits, fainting, weakness, "
        "numbness, tingling, tremor, memory, speech and balance problems",
        "stroke and transient ischaemic attack, meningitis and encephalitis, bleeding in the head "
        "(sudden worst-ever headache), a first seizure, spinal cord compression, raised pressure in the head",
        "pain or weakness explained by a joint, muscle or bone; low mood and anxiety on their own",
    ),
    "Pulmonology": Specialty(
        "the lungs and airways: cough, wheeze, breathlessness, sputum, coughing blood, pain on "
        "breathing in, snoring and sleep-related breathing problems",
        "pneumonia, a severe asthma or COPD attack, pulmonary embolism, a collapsed lung, "
        "tuberculosis, low oxygen saturation",
        "nose and throat complaints with a clear chest (ENT); breathlessness that is cardiac",
    ),
    "Nephrology": Specialty(
        "the kidneys and fluid balance: swelling of the legs or face, foamy or bloody urine, "
        "passing very little urine, kidney disease, high blood pressure caused by the kidneys",
        "acute kidney injury, kidney infection with sepsis, dangerous potassium or fluid "
        "overload, nephrotic and nephritic syndromes",
        "bladder, prostate and stone problems that need a procedure (Urology)",
    ),
    "Endocrinology": Specialty(
        "hormones and metabolism: diabetes, thyroid disease, weight change without explanation, "
        "excessive thirst and urination, heat or cold intolerance, growth and puberty problems",
        "diabetic ketoacidosis and very high blood sugar, low blood sugar, thyroid storm, "
        "adrenal crisis",
        "tiredness or weight change better explained by infection, mood, diet or another organ",
    ),
    "Oncology": Specialty(
        "cancer: unexplained lumps, weight loss, night sweats, persistent unexplained bleeding, "
        "and any symptom in a patient with known or treated cancer",
        "fever in a patient on chemotherapy, spinal cord compression, a lump or bleeding that "
        "needs urgent cancer investigation",
        "short-lived symptoms with an ordinary explanation and no feature suggesting cancer",
    ),
    "General Surgery": Specialty(
        "the abdomen and soft tissues where an operation may be needed: severe or localised "
        "abdominal pain, hernias, lumps, abscesses, wounds, rectal bleeding and anal pain",
        "appendicitis, a perforated or obstructed bowel, a strangulated hernia, gallbladder "
        "infection, an abscess needing drainage, peritonitis",
        "abdominal symptoms that are clearly medical (gastroenteritis, reflux) with a soft, "
        "non-tender abdomen",
    ),
    "Orthopedic Surgery": Specialty(
        "bones, joints, muscles, tendons and ligaments: injuries, fractures, back and neck pain, "
        "joint pain, swelling and stiffness, sports injuries",
        "a fracture or dislocation, an infected joint (hot, swollen, with fever), cauda equina "
        "syndrome, compartment syndrome, a bone tumour",
        "limb pain or weakness that comes from a nerve, a blood vessel or the heart",
    ),
    "Neurosurgery": Specialty(
        "brain and spine conditions that may need an operation: head injury, a slipped disc "
        "pressing on nerves, spinal injury, known brain tumours or shunts",
        "bleeding inside the skull after injury, cauda equina syndrome, spinal cord compression, "
        "a blocked shunt, raised pressure in the head",
        "headache, dizziness or back pain with no injury, no neurological deficit and no "
        "sign of pressure (Neurology or Orthopedic Surgery)",
    ),
    "Ophthalmology": Specialty(
        "the eyes and vision: red or painful eye, blurred or double vision, loss of vision, "
        "flashes and floaters, eye injuries, eyelid problems",
        "sudden loss of vision, acute glaucoma (painful red eye with haloes and vomiting), "
        "retinal detachment, a chemical or penetrating eye injury, infection around the eye",
        "headache or dizziness with no eye or vision complaint",
    ),
    "Urology": Specialty(
        "the urinary tract and the male reproductive organs: burning or frequent urination, blood "
        "in the urine, loin pain, kidney stones, prostate and testicular problems",
        "testicular torsion, a blocked and infected kidney, inability to pass urine, "
        "visible blood in the urine, infection of the scrotum or perineum",
        "kidney disease without obstruction (Nephrology); female pelvic problems (Obstetrics & Gynecology)",
    ),
    "Otolaryngology (ENT)": Specialty(
        "ear, nose, throat, mouth and neck: sore throat, earache, hearing loss, blocked nose, "
        "sinus pain, nosebleeds, hoarse voice, neck lumps, vertigo from the ear, mouth and dental pain",
        "a threatened airway (drooling, muffled voice, noisy breathing), a quinsy or deep neck "
        "infection, a nosebleed that will not stop, sudden hearing loss, a persistent neck lump",
        "cough and breathlessness coming from the chest (Pulmonology)",
    ),
    OBGYN: Specialty(
        "pregnancy and the female reproductive system: period problems, pelvic pain, vaginal "
        "bleeding or discharge, pregnancy and post-delivery complaints, menopause, breast symptoms",
        "ectopic pregnancy, miscarriage, pre-eclampsia, heavy bleeding, ovarian torsion, "
        "pelvic infection; any abdominal pain in a woman who could be pregnant",
        "male patients, and women whose complaint has no pelvic, menstrual, breast or "
        "pregnancy element",
    ),
    "Psychiatry": Specialty(
        "mental health and behaviour: low mood, anxiety and panic, sleep problems, hearing or "
        "seeing things, confusion, self-harm, alcohol and drug use, eating problems",
        "thoughts of suicide or of harming others, psychosis, delirium from a physical illness, "
        "alcohol or drug withdrawal, a physical disease presenting as a mental one",
        "physical symptoms with no psychological element, once you have considered whether "
        "stress or panic could explain them",
    ),
    "Anesthesiology": Specialty(
        "pain medicine and fitness for a procedure: severe, long-standing or nerve-type pain "
        "that ordinary treatment has not controlled, and the risks of sedation or anaesthesia",
        "pain out of proportion to the findings, a patient likely to need an urgent operation "
        "who has a difficult airway, heart or lung disease, or a past anaesthetic reaction",
        "pain that is new, mild or already explained and treated by another specialty, and "
        "any case where no procedure or pain service is in question",
    ),
}

# Where the report may send the patient.
DEPARTMENTS = [*SPECIALISTS, GENERAL_OPD, EMERGENCY_DEPT]

SPECIALIST_OUTPUT = """Reply with ONE JSON object and nothing else:
{
  "relevant": true or false,
  "assessment": "2-4 sentences: your reading of the case from your specialty",
  "conditions": [{"name": "...", "likelihood": "low" | "medium" | "high", "reasoning": "one sentence, citing [S1] etc. where a guideline passage supports it",
                  "first_line": "the usual first-line treatment for this condition in this patient (generic medicine names), or the test that must come before treatment"}],
  "urgency": "routine" | "soon" | "urgent" | "emergency",
  "ask": ["up to 3 things the treating doctor should check or ask"]
}
How to work:
1. Decide first whether this patient's problem is yours. relevant is true only if
   a reported symptom or finding comes from the organs or problems of your field,
   or a dangerous condition of your field has to be ruled out because something in
   THIS case points to it. A symptom that every field shares (fever, tiredness,
   body aches, poor appetite) does not make a case yours on its own. If it is not
   yours, set relevant to false, give the reason in one sentence, leave conditions
   and ask empty, and stop: you step aside and take no further part. Do not
   stretch the case to fit your field. But when the main complaint is one your
   field lists (for example burning urination for Urology), it IS yours: stay.
2. If it is yours, reason from THIS patient: age, gender, each symptom, how long it
   has lasted (hours, days or months change what is likely), medication already
   taken and whether it helped, and every vital sign. Say which details point
   towards and which point away from your conclusions. Normal vitals make a
   serious illness less likely; vitals that were not measured tell you nothing.
3. Think of what is common first. The patient is in India: weigh conditions by how
   often they occur in an Indian hospital's outpatients for this age and gender,
   and remember infections that are common there. A common condition that fits
   beats a rare one that also fits.
4. Check the dangerous conditions of your field one by one against the case. Name
   one only when something in the case supports it, and say in "ask" what would
   rule it out.
5. conditions: at most 3, most likely first, only within your specialty, each a
   specific diagnosis rather than a symptom or a category. likelihood is "high"
   only when the picture is typical, "medium" when it fits but other causes fit as
   well, "low" when it is a must-rule-out. Never "high" for a condition
   whose key feature the case does not mention (no missed period, no
   bleeding, no fainting: an ectopic pregnancy is at most "low"). Use the name an
   Indian doctor would write (scabies, not acariasis; allergic rhinitis, not hay
   fever), even when a knowledge-base candidate is the same disease under an
   older or textbook name. Never name a condition whose
   defining features the patient does not have. The evidence scores come from
   symptom overlap alone: they are a reminder list, not a verdict.
6. urgency is how soon this patient must be seen for the problems in your field.
   "emergency" only when a red flag is PRESENT in the case (severe or sudden
   pain, fainting, heavy bleeding, breathing difficulty, confusion, abnormal
   vital signs); a dangerous condition you only need to rule out, with
   normal vitals and a mild account, is "soon", at most "urgent". Give the
   concrete reason in your assessment for urgent or emergency.
7. ask: specific and useful to the doctor: an examination finding, a question
   or a basic test that would separate your conditions. No generic advice.
8. The case may include guideline passages labelled [S1], [S2] ... (Indian
   Standard Treatment Workflows, the National Formulary of India, WHO and
   others). Use their "when to suspect", warning-sign and referral criteria
   to judge THIS patient, and cite the label in reasoning when you rely on
   one. A passage about a condition does not make that condition likely: the
   patient must have its features.
Use only what is in the case. Never invent a symptom, a test result or a history."""

CHAIR_OUTPUT = """Reply with ONE JSON object and nothing else:
{
  "summary": "2-3 plain sentences restating the patient's complaint",
  "discussion": "2-4 sentences: where the specialists agreed, where they differed, and how you resolved it",
  "possible_conditions": [{"name": "...", "likelihood": "low" | "medium" | "high", "probability": 0-100, "reasoning": "one sentence", "raised_by": "specialty"}],
  "urgency": "routine" | "soon" | "urgent" | "emergency",
  "department": "the ONE department the patient should be sent to",
  "medicines": [{"name": "...", "purpose": "what it is used for in this situation"}],
  "lifestyle_advice": ["up to 4 short points on diet, rest, activity or habits"],
  "doctor_notes": ["up to 5 short points the treating doctor should check or ask"]
}
Rules:
- Only the specialists whose opinions are given took part. Those listed as having
  stepped aside judged the case to be outside their field: do not attribute
  anything to them. When no specialist took part, the case belongs to general
  medicine: reason it through yourself.
- You cover general medicine: everyday infections and fevers (viral fever, common
  cold, flu, gastroenteritis) and, because the patient is in India, dengue,
  malaria and typhoid when the fever's pattern, duration or season fits them.
  Fever for under three days with no localising symptom and normal vitals is
  most likely "Viral fever"; typhoid needs about a week of fever, malaria a
  pattern of chills or travel to an endemic area, dengue severe body or eye
  pain, rash or bleeding. Hepatitis needs jaundice, dark urine or right
  upper abdominal pain. Do not list these without their features.
- urgency "emergency" needs a red flag present in the case, not a condition
  that only has to be ruled out. Suspected dengue without a warning sign
  (abdominal pain, persistent vomiting, bleeding, drowsiness or restlessness,
  breathlessness, low blood pressure) is "urgent" (tested today), not an
  emergency: a rash or high fever is not a warning sign. Its department is
  "{general}".
- Lower abdominal pain in a young woman with normal vitals and no red flag:
  think first of period pain, a urinary infection, gastroenteritis or
  constipation, and appendicitis as the must-rule-out. Pelvic infection needs
  fever, discharge or pain on examination reported in the case.
- A known condition the patient reports (diabetes, hypertension, asthma) is
  named as the case shows it: an adult with diabetes on tablets has type 2
  diabetes (type 1 needs insulin from a young age); high sugar after tablets
  ran out is uncontrolled type 2 diabetes. Do not guess a type the case does
  not show.
- possible_conditions: at most 5, most likely first. Weigh the specialists against
  each other; do not simply merge their lists. The knowledge-base scores only
  measure how many symptoms a condition shares with the case: never list a
  condition because of its score. List one only if what the patient reported
  points to it, and a less likely one only if a specific feature of this case
  makes it necessary to rule out. A condition whose defining features the
  patient does not have is not listed (no common cold without a nose or
  throat symptom, no urinary infection without a urinary symptom). For a
  common, mild presentation, two or three conditions are enough.
  Use the name an Indian doctor would write on a prescription (scabies, not
  acariasis; allergic rhinitis, not hay fever; type 2 diabetes mellitus), even
  when a knowledge-base candidate is the same disease under another name.
  One condition per entry, no "A / B".
  probability: your estimate, in percent, that this is the patient's
  condition; the numbers of all listed conditions add up to at most 100.
  raised_by is the specialty on this panel that argued for it, or "{general}"
  for one you raised yourself.
- department: where the patient should go for your MOST LIKELY condition, not for
  one that only needs ruling out. The specialty that owns it (usually the one that
  raised it); "{general}" when no
  specialty does (a viral fever, a cold, a mild stomach upset); "{emergency}" when
  the urgency is emergency. One name from this list, copied exactly: {roster}.
- medicines: hints for the report writer, at most 5, generic names: the first-line
  medicine for each condition you listed as likely (as the guideline passages
  [S1].. or the specialists' first_line give it), and for each main complaint
  (fever or pain, itching, cough, acidity, loose stools ...). A condition that
  needs a test before treatment (malaria, dengue, typhoid, tuberculosis) gets
  symptom relief only. Never give a dose here.
- Cite guideline passages [S1].. in reasoning where they support a condition.
  The passages were looked up for this presentation, including dangerous
  conditions that only have to be ruled out: a condition named in a passage
  is NOT likely unless THIS patient has its defining features. Diabetic
  ketoacidosis or a hyperosmolar state needs vomiting, abdominal pain, deep
  or fast breathing, drowsiness or confusion, or marked dehydration; thirst,
  passing urine often and tiredness alone are high sugar (uncontrolled
  diabetes), with DKA at most a "low" must-rule-out.
- lifestyle_advice is for the patient: plain words, no medicine names.
- Take the highest urgency any specialist justified with a concrete reason."""


@dataclass
class PanelResult:
    opinions: list[dict]  # {"specialist", "relevant", "assessment", "conditions", "urgency", "ask"}
    conclusion: dict  # the chair's JSON
    model: str


class PanelError(Exception):
    pass


def parse_json(raw: str) -> dict:
    """The JSON object in a model reply, tolerating code fences and chatter."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise PanelError("A panel member did not answer in JSON") from None
        try:
            value = json.loads(text[start : end + 1])
        except ValueError:
            raise PanelError("A panel member did not answer in JSON") from None
    if not isinstance(value, dict):
        raise PanelError("A panel member did not answer with a JSON object")
    return value


CHAIR_STORY = (
    "You are an experienced general physician in an Indian hospital, chairing a "
    "multi-specialty panel. You listen to every specialist who took part, notice where "
    "they disagree, and decide what the patient's doctor most needs to know. You are "
    "cautious: when in doubt you choose the safer urgency."
)


def backstory(name: str) -> str:
    """What makes an agent this specialist rather than a general model."""
    s = SPECIALISTS[name]
    return (
        f"You are a senior consultant in {name} with twenty years of practice, sitting on "
        f"an Indian hospital's pre-consultation panel.\n"
        f"Your field: {s.scope}.\n"
        f"What you must never miss: {s.never_miss}.\n"
        f"What is not yours: {s.not_theirs}.\n"
        "You think only about the patient in front of you and only from your own specialty. "
        "When a case is outside your field you say so in one sentence and step aside; you "
        "never guess in a colleague's territory. You take the supplied evidence seriously "
        "without being bound by it, and you do not prescribe: the treating doctor decides."
    )


class SpecialistPanel:
    """Runs the panel on Gemini through CrewAI."""

    def __init__(self, api_key: str, chair_model: str, specialist_model: str = ""):
        self._api_key = api_key
        self._chair_model = chair_model
        # Specialists answer in parallel and their opinions are weighed by
        # the chair, so they can run on a faster model than the chair does.
        self._specialist_model = specialist_model or chair_model
        self.name = f"crewai-panel:{self._specialist_model}+{chair_model}"

    async def _ask(self, role: str, goal: str, story: str, task: str, chair: bool) -> str:
        """One agent's answer, as text. The chair thinks more."""
        from crewai import LLM, Agent, Crew, Process, Task

        extra = {}
        if chair:
            from google.genai import types

            # Caps the reasoning before the answer: the chair's default
            # thinking took about 20 s of every report.
            extra["thinking_config"] = types.ThinkingConfig(thinking_budget=1024)
        name = self._chair_model if chair else self._specialist_model
        from google.genai import types as genai_types

        # The client's own limit (milliseconds) ends a stuck request; the one
        # in with_retries stops the wait. (CrewAI's Gemini provider ignores a
        # plain `timeout`.)
        llm = LLM(
            model=f"gemini/{name}", api_key=self._api_key, temperature=0.2,
            client_params={"http_options": genai_types.HttpOptions(timeout=int(CALL_TIMEOUT * 1000))},
            **extra,
        )  # fmt: skip
        agent = Agent(
            role=role, goal=goal, backstory=story, llm=llm,
            allow_delegation=False, verbose=False,
        )  # fmt: skip
        job = Task(description=task, expected_output="One JSON object in the format given.", agent=agent)
        crew = Crew(agents=[agent], tasks=[job], process=Process.sequential, verbose=False)
        return (await with_retries(crew.kickoff_async, role)).raw

    async def run(self, case: str, specialists: list[str], progress=None) -> PanelResult:
        """Each specialist reads the case at the same time. Those who find it
        is not theirs step aside; the chair concludes from the rest.
        `progress` (a `progress.ReportProgress`) hears each answer."""

        async def opinion(name: str) -> dict:
            raw = await self._ask(
                f"{name} specialist",
                "Decide whether this patient's problem belongs to your specialty and, if it "
                "does, give a specific, reasoned opinion on it.",
                backstory(name),
                f"{case}\n\nAssess this case as the panel's {name} specialist.\n{SPECIALIST_OUTPUT}",
                chair=False,
            )
            try:
                parsed = parse_json(raw)
            except PanelError:
                # One garbled opinion should not sink the panel; keep its text.
                parsed = {"relevant": True, "assessment": raw.strip()[:600]}
            relevant = bool(parsed.get("relevant", True))
            if progress is not None:
                progress.answered(name, "took_part" if relevant else "stepped_aside")
            return {**parsed, "specialist": name, "relevant": relevant}

        async def heard(name: str) -> dict:
            try:
                return await opinion(name)
            except Exception:
                if progress is not None:
                    progress.answered(name, "unavailable")
                raise

        answers = await asyncio.gather(*(heard(n) for n in specialists), return_exceptions=True)
        opinions = []
        for name, answer in zip(specialists, answers):
            if isinstance(answer, BaseException):
                # A specialist who could not be reached is left out, not invented.
                log.warning("The %s specialist could not answer: %s", name, answer)
            else:
                opinions.append(answer)
        if specialists and not opinions:
            raise PanelError("No specialist on the panel could answer")
        # Everyone may step aside (a plain viral fever is nobody's specialty):
        # the chair, a general physician, then concludes on its own.
        taking_part = [o for o in opinions if o["relevant"]]

        stepped_aside = [o["specialist"] for o in opinions if not o["relevant"]]
        spoken = "\n\n".join(
            f"{o['specialist']}:\n" + json.dumps({k: v for k, v in o.items() if k not in ("specialist", "relevant")})
            for o in taking_part
        )
        if progress is not None:
            progress.at("chair")
        try:
            conclusion = await self._ask(
                "Panel chair",
                "Turn the specialists' opinions into one balanced, safe conclusion.",
                CHAIR_STORY,
                f"{case}\n\n"
                + (f"Opinions of the specialists who took part:\n\n{spoken}\n\n" if spoken else "No specialist found this case within their field.\n\n")
                + (f"Stepped aside, case outside their field: {', '.join(stepped_aside)}.\n\n" if stepped_aside else "")
                + "Chair the discussion and write the panel's conclusion.\n"
                + CHAIR_OUTPUT.replace("{roster}", ", ".join(DEPARTMENTS))
                .replace("{general}", GENERAL_OPD)
                .replace("{emergency}", EMERGENCY_DEPT),
                chair=True,
            )
        except Exception as e:
            raise PanelError(f"The specialist panel could not run: {e}") from e
        return PanelResult(opinions, parse_json(conclusion), self.name)


# The forms the local model fills in (Ollama structured output): in plain
# JSON mode MedGemma's chair answer broke the JSON twice (2026-10-29).
_T = {"type": "string", "maxLength": 300}
_LIST = {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 200}}
_LEVEL = {"type": "string", "enum": ["low", "medium", "high"]}
_URGENCY = {"type": "string", "enum": ["routine", "soon", "urgent", "emergency"]}


def _form(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props)}


CHAIR_FORM = _form({
    "summary": _T, "discussion": _T,
    "possible_conditions": {"type": "array", "maxItems": 5, "items": _form({
        "name": {"type": "string", "maxLength": 120}, "likelihood": _LEVEL,
        "probability": {"type": "integer"}, "reasoning": _T, "raised_by": {"type": "string", "maxLength": 80}})},
    "urgency": _URGENCY, "department": {"type": "string", "maxLength": 80},
    "medicines": {"type": "array", "maxItems": 5, "items": _form(
        {"name": {"type": "string", "maxLength": 80}, "purpose": {"type": "string", "maxLength": 160}})},
    "lifestyle_advice": _LIST, "doctor_notes": _LIST,
})  # fmt: skip
SPECIALIST_FORM = _form({
    "relevant": {"type": "boolean"}, "assessment": _T,
    "conditions": {"type": "array", "maxItems": 3, "items": _form({
        "name": {"type": "string", "maxLength": 120}, "likelihood": _LEVEL, "reasoning": _T,
        "first_line": {"type": "string", "maxLength": 200}})},
    "urgency": _URGENCY, "ask": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 200}},
})  # fmt: skip


class LocalPanel(SpecialistPanel):
    """The same panel, with the same agents and instructions, on the local
    medical model (no internet). Each agent is asked directly in JSON mode:
    CrewAI's own prompt scaffolding adds hundreds of tokens per call, which
    a laptop CPU pays for in tens of seconds. Ollama answers one call at a
    time, so the specialists take turns."""

    def __init__(self, llm):
        self._llm = llm  # an `llm.OllamaLlm` with clinical=True
        self.name = f"local-panel:{llm.name}"

    async def _ask(self, role: str, goal: str, story: str, task: str, chair: bool) -> str:
        answer = await self._llm.json(f"{story}\n\nYour role: {role}. Your goal: {goal}", task,
                                      answer_tokens=1500 if chair else 700,
                                      schema=CHAIR_FORM if chair else SPECIALIST_FORM)
        return json.dumps(answer)
