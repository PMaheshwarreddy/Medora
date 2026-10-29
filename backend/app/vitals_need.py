"""Whether a complaint calls for vitals at all.

A knee sprain or low mood does not need a heart rate and oxygen reading, and
making every patient wear the band slows the kiosk down. One quick model
call decides from what the patient said; anything uncertain, and any
failure, means vitals ARE taken. Used by the form flow (`POST
/api/intake/vitals-check`) and by the voice agent (`voice.py`).
"""

import logging

from .llm import Llm, LlmError

log = logging.getLogger("medora.vitals_need")

_DECIDE = """You decide whether a hospital kiosk should measure a patient's \
vital signs (heart rate and blood oxygen) before they see a doctor. Return \
ONE JSON object: {"needed": true or false, "reason": "one short, kind \
sentence for the patient"}

Vitals ARE needed when any reported symptom could involve: fever, chills or
infection; breathing, cough or chest; the heart or circulation (palpitations,
swollen legs, fainting, dizziness); headache, weakness, numbness or
confusion; bleeding; vomiting, diarrhoea or abdominal pain; dehydration;
pregnancy; diabetes or blood pressure; an allergic reaction; feeling
generally unwell or very tired; anything sudden or severe; or panic or
anxiety WITH physical symptoms.

Vitals ARE also needed after a serious accident (a road accident, a fall
from a height, a blow to the head or chest).

Vitals are NOT needed for, on their own: pain or stiffness in a muscle, a
joint, the back or a limb, including a sprain, twist or strain from sport
or lifting, as long as there is no fever, no hot and swollen joint, no
numbness and no serious accident; a
skin problem without fever; low mood, stress, worry or poor sleep without
physical symptoms; an eye, ear or tooth problem without fever; a question
about medicines, a prescription, a report or a follow-up.

When in doubt, needed is true. The reason says, in plain words, why the
measurement is or is not needed (for example "Your knee pain does not need
a heart or oxygen check.")."""


async def vitals_needed(
    llm: Llm, symptoms: str, age: int | None = None, duration: str = "", language: str = "en"
) -> tuple[bool, str]:
    """(needed, reason). Only a clear "not needed" from the hosted model
    skips the vitals."""
    if not symptoms.strip():
        return True, ""
    # The very young and the old get vitals whatever the complaint.
    if age is not None and (age < 5 or age >= 65):
        return True, ""
    lines = [f"Symptoms, in the patient's words: {symptoms}"]
    if duration:
        lines.append(f"Duration: {duration}")
    if age is not None:
        lines.append(f"Age: {age}")
    system = _DECIDE
    if language == "ml":
        # The patient reads the reason; the symptoms may be in Malayalam too.
        system += "\nWrite the reason in simple Malayalam, in Malayalam script."
    try:
        raw = await llm.json(system, "\n".join(lines), thinking=0)
    except LlmError as e:
        log.warning("Could not decide on vitals, taking them: %s", e)
        return True, ""
    if getattr(llm, "name", "").startswith("ollama"):
        return True, ""  # the small local model may not waive a measurement
    needed = raw.get("needed") is not False
    reason = str(raw.get("reason") or "").strip()[:200]
    return needed, "" if needed else reason
