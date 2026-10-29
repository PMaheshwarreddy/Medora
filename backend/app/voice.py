"""Voice intake conversation.

Wire protocol on `/ws/voice` (the browser never talks to the model directly,
so the API key stays on the server):

  browser -> server
    binary                 microphone audio, PCM16 mono 16 kHz
    {"type": "start", "smartBand": bool, "language": "auto" | "en" | "ml",
     "known": {...intake fields}, "vitalsTaken": bool}
                           "auto": Medora greets in English and follows the
                           patient's language (answers `language`); "ml"
                           greets in Malayalam. `known`: details the kiosk
                           already holds (the page was reloaded mid-visit),
                           so Medora carries on instead of starting over
    {"type": "vitals", "captured": bool, ...readings}   answer to request_vitals
    {"type": "pause"} | {"type": "resume"}   staff paused the conversation
                           (noise, an interruption); on resume Medora repeats
                           her last question

  server -> browser
    binary                 Dr. Medora's voice, PCM16 mono 24 kHz
    {"type": "ready"} | {"type": "unavailable", "reason": str}
    {"type": "transcript", "role": "patient" | "medora", "text": str}
    {"type": "interrupted"}        patient spoke over Medora: stop playback
    {"type": "turn_complete"}
    {"type": "intake", "fields": {...}}   details heard so far
    {"type": "language", "language": "en" | "ml"}   the patient's choice
    {"type": "request_vitals"}
    {"type": "vitals_skipped", "reason": str}   this complaint needs no vitals
    {"type": "complete"}           intake finished: go to review
    {"type": "error", "message": str}
"""

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from .settings import Settings

log = logging.getLogger("medora.voice")

Inbound = bytes | dict
Emit = Callable[[bytes | dict], Awaitable[None]]


@dataclass
class VoiceContext:
    smart_band: bool
    # Decides from the symptoms (and age, if known) whether vitals are
    # needed: (needed, reason). None means always take them (the default
    # since 2026-10-29, `Settings.vitals_always`).
    vitals_check: Callable[[str, int | None], Awaitable[tuple[bool, str]]] | None = None
    # en | ml: the language Dr. Medora speaks; "auto" until the patient has
    # said which they are comfortable with (set_language).
    language: str = "en"
    # Details the kiosk already holds when the conversation (re)starts, e.g.
    # after the page was reloaded: Medora carries on instead of asking again.
    known: dict = field(default_factory=dict)
    # The band has already measured this visit: it is not shown again.
    vitals_taken: bool = False


class IntakeTools:
    """The model's tool calls, kept apart from the Gemini plumbing so they
    can be tested: saving details, deciding on vitals, and making sure the
    band is used at most once per conversation.

    `call` returns the response to send now, or None when the response
    waits for the kiosk (a vitals measurement); `vitals_measured` then
    gives that late response."""

    def __init__(self, ctx: VoiceContext, emit: Emit):
        self._ctx = ctx
        self._emit = emit
        # What the patient has said so far (and what the kiosk already held),
        # for the vitals decision and for carrying on after a reconnect.
        self.heard: dict = dict(ctx.known)
        # The answer to the measurement, reused if the model asks again.
        self._vitals_answer: dict | None = (
            {"result": "The vitals were already measured at this kiosk.", "note": self._TAKEN}
            if ctx.vitals_taken else None
        )  # fmt: skip
        # None until decided; then whether vitals are needed.
        self._decision: bool | None = None
        self.pending_vitals_id: str | None = None
        # The band is measuring but the call that asked for it is gone (the
        # line to the model was re-opened, or the call was cancelled): the
        # result then goes to the model as a message instead.
        self.vitals_waiting = False
        self._finish_refusals = 0
        self.finishing = False

    _TAKEN = "Vitals were taken once already; do not ask again."
    _NO_DEVICE = {"result": "This kiosk has no vitals device. Continue without them."}
    _SKIP = {
        "result": "Vitals are not needed for this complaint. Do not mention vitals "
        "or the band; continue with the next step."
    }
    _NOT_YET = {
        "result": "Not finished: the vitals have not been taken yet. In one short sentence ask "
        "the patient to put on the band and follow the screen, and call request_vitals in the "
        "same reply. Call finish_intake after that."
    }
    # How often finishing is refused for want of vitals before it is let
    # through (the review screen then takes them).
    MAX_FINISH_REFUSALS = 2

    async def _needed(self) -> bool:
        if self._decision is None:
            needed, reason = True, ""
            if self._ctx.vitals_check is not None:
                needed, reason = await self._ctx.vitals_check(
                    str(self.heard.get("symptoms", "")), self.heard.get("age")
                )
            self._decision = needed
            if not needed:
                await self._emit({"type": "vitals_skipped", "reason": reason})
        return self._decision

    async def call(self, call_id: str, name: str, args: dict) -> dict | None:
        if name == "update_intake":
            fields = clean_intake(args)
            if fields:
                self.heard.update(fields)
                await self._emit({"type": "intake", "fields": fields})
            return {"result": "saved"}
        if name == "vitals_needed":
            if not self._ctx.smart_band:
                return {"needed": False, **self._NO_DEVICE}
            if self._vitals_answer is not None:
                return {"needed": False, **self._vitals_answer}
            if await self._needed():
                return {"needed": True}
            return {"needed": False, **self._SKIP}
        if name == "request_vitals":
            if not self._ctx.smart_band:
                return self._NO_DEVICE
            if self._vitals_answer is not None:
                return self._vitals_answer  # asked again: never measure twice
            if self.pending_vitals_id is not None:
                return {"result": "The measurement is already running; wait for it."}
            if not await self._needed():
                return self._SKIP
            self.pending_vitals_id = call_id
            await self._emit({"type": "request_vitals"})
            return None
        if name == "set_language":
            language = str(args.get("language", "")).strip().lower()
            if language not in SPEECH:
                return {"result": "Use en for English or ml for Malayalam."}
            self._ctx.language = language
            await self._emit({"type": "language", "language": language})
            return {"result": f"Language set. From now on speak only {SPEECH[language][0]}."}
        if name == "finish_intake":
            # Vitals are a must: the model once said "I'd like to take your
            # vitals" without calling request_vitals, then finished.
            missing = (
                self._ctx.smart_band
                and self._vitals_answer is None
                and self.pending_vitals_id is None
                and not self.vitals_waiting
                and (self._decision is not False)
            )
            if missing and self._finish_refusals < self.MAX_FINISH_REFUSALS:
                self._finish_refusals += 1
                return self._NOT_YET
            self.finishing = True
            return {"result": "ok"}
        return {"result": "unknown tool"}

    @property
    def vitals_done(self) -> bool:
        """The band has measured (or failed) once in this conversation."""
        return self._vitals_answer is not None

    def drop_pending(self) -> None:
        """The pending request_vitals call can no longer be answered (a new
        line to the model, or the model cancelled it); the measurement goes
        on and its result is sent as a message."""
        if self.pending_vitals_id is not None:
            self.pending_vitals_id = None
            self.vitals_waiting = True

    def vitals_measured(self, item: dict) -> tuple[str | None, dict] | None:
        """The kiosk's answer to request_vitals, as (call id, response); the
        call id is None when the call was dropped (send it as a message)."""
        if self.pending_vitals_id is None and not self.vitals_waiting:
            return None
        call_id, self.pending_vitals_id = self.pending_vitals_id, None
        self.vitals_waiting = False
        measured = [
            label
            for key, label in (
                ("heartRate", "heart rate"), ("spo2", "oxygen level"),
                ("temperatureC", "temperature"), ("systolic", "blood pressure"),
            )
            if item.get(key) is not None
        ]  # fmt: skip
        result = (
            {"result": "Vitals measured: " + ", ".join(measured) + ". Do not read the numbers out."}
            if item.get("captured") and measured
            else {"result": "Vitals are unavailable just now. Say in one short sentence that they "
                  "will be taken on the next screen, then continue."}
        )
        self._vitals_answer = {**result, "note": self._TAKEN}
        return call_id, result


class VoiceProvider(Protocol):
    name: str

    async def run(
        self, ctx: VoiceContext, inbound: AsyncIterator[Inbound], emit: Emit
    ) -> None: ...


INTAKE_FIELDS = {
    "name": ("string", "The patient's full name"),
    "age": ("integer", "Age in years"),
    "gender": ("string", "One of: male, female, other"),
    "phone": ("string", "Phone number, digits only"),
    "email": ("string", "Email address, if the patient offers one"),
    "symptoms": ("string", "All symptoms reported so far, in the patient's words"),
    "duration": ("string", "How long the symptoms have lasted"),
    "medications": ("string", "Medication already taken for this, or 'none' if the patient said they took none"),
    "allergies": ("string", "Allergies to medicines, injections or anything else, or 'none' if the patient said they have none"),
    "chronic_conditions": ("string", "Long-term conditions such as diabetes, high blood pressure, asthma, or 'none' if the patient said they have none"),
    "regular_medicines": ("string", "Medicines taken every day for a long-term condition, or 'none' if the patient said they take none"),
    "weight_kg": ("number", "Weight in kilograms, when asked"),
    "pregnancy": ("string", "Only if asked: yes, no or unsure"),
    "habits": ("string", "Only if asked (adults 18 and over): smoking, tobacco and alcohol, as said, e.g. 'smokes 10 cigarettes a day, drinks at weekends', or 'none'"),
}


# Spoken language and the Live API's language code for each kiosk language.
SPEECH = {"en": ("English", "en-US"), "ml": ("Malayalam", "ml-IN")}
# What the patient's speech is transcribed as (shown on the kiosk screen).
TRANSCRIBE_LANGUAGES = ["en-IN", "ml-IN"]


# Dr. Medora's first words, in each language. The Malayalam is fixed here
# because the model once turned it round ("how can you help me?").
GREETING = {
    "en": "Hi, I'm Dr. Medora. How can I help you today?",
    "ml": "നമസ്കാരം, ഞാൻ ഡോക്ടർ മെഡോറ. ഇന്ന് എനിക്ക് നിങ്ങളെ എങ്ങനെ സഹായിക്കാൻ കഴിയും?",
}
# Said instead of the greeting when a conversation restarts mid-visit.
CARRY_ON = {"en": "Let's carry on.", "ml": "നമുക്ക് തുടരാം."}

_ASK_LANGUAGE = f"""Step 1, greeting and language. Your first words are exactly, \
in English only: "{GREETING["en"]}" Say nothing \
more, and no Malayalam yet. Then listen:
- If the patient answers in Malayalam, call set_language with ml at once and \
carry on ONLY in Malayalam, with the problem they told you.
- If they answer in English and tell you their problem, call set_language \
with en and carry on in English.
- If they only greet you ("hi", "hello") without saying their problem, ask in \
English: "Which language are you comfortable with, English or Malayalam?" \
When they answer, call set_language, then ask how you can help, in that \
language (in Malayalam exactly: "{GREETING["ml"].split(". ", 1)[1]}").
If they ask for the other language later, call set_language again and switch."""


def _language_rules(language: str) -> str:
    if language not in ("ml", "auto"):
        return ""
    who = "The patient chose Malayalam." if language == "ml" else "If the patient chooses Malayalam:"
    return f"""

LANGUAGE
{who} Speak ONLY Malayalam, the simple, polite, everyday \
Malayalam spoken in Kerala, addressing the patient respectfully (നിങ്ങൾ). Medicine \
names and numbers may stay in English as people say them. One question per reply in \
Malayalam too: never join two questions with ഒപ്പം, അതോ or അല്ലെങ്കിൽ.
Keep who does what right: YOU help the patient, so "how can I help you" is \
"എനിക്ക് നിങ്ങളെ എങ്ങനെ സഹായിക്കാൻ കഴിയും?", never "നിങ്ങൾക്ക് എന്നെ...". \
An acknowledgement is a statement: "ശരി, പനിയും വിറയലും ഉണ്ട്.", never \
"പനിയുണ്ടല്ലേ?". Use these exact Malayalam questions where they fit: \
age: നിങ്ങളുടെ പ്രായം എത്രയാണ്? \
gender: നിങ്ങൾ പുരുഷനാണോ സ്ത്രീയാണോ? \
how long: ഇത് തുടങ്ങിയിട്ട് എത്ര ദിവസമായി? \
allergies: ഏതെങ്കിലും മരുന്നിനോ ഇഞ്ചക്ഷനോ അലർജിയുണ്ടോ? \
pregnancy: ഇപ്പോൾ ഗർഭിണിയാണോ, അതോ ആകാൻ സാധ്യതയുണ്ടോ? \
habits: പുകവലിക്കുകയോ പുകയില ഉപയോഗിക്കുകയോ ചെയ്യാറുണ്ടോ? and, as a reply of its own: മദ്യപിക്കാറുണ്ടോ? \
band: ദയവായി ബാൻഡ് ധരിച്ച് സ്ക്രീനിൽ കാണിക്കുന്നത് പോലെ ചെയ്യുക.
When you save details with update_intake: write symptoms, duration, \
medications and allergies in Malayalam script, as the patient said them; write \
the name in English letters; phone digits only; gender as male, female or other; \
pregnancy as yes, no or unsure; habits in Malayalam script."""


def _vitals_step(smart_band: bool, decide: bool) -> str:
    if not smart_band:
        return "Step 4 is skipped: this kiosk has no vitals device. Do not mention vitals."
    first = (
        "First call vitals_needed, without saying anything about vitals. If it answers that "
        "vitals are not needed, do not mention vitals or the band at all and go straight to "
        "step 5. If they are needed, carry on as follows. "
        if decide
        else "Every patient has their vitals taken: never skip this step. "
    )
    return (
        "Step 4, vitals. " + first +
        "In ONE reply, say one short sentence asking the patient to put on the band and follow "
        "the screen, and call request_vitals in that same reply. The kiosk shows the band ONLY "
        "when you call request_vitals, so never say you will take the vitals without calling it, "
        "and never ask the patient to tell you when the band is on: the screen guides them and "
        "starts the measurement, which takes about a minute. While it runs, say nothing and ask "
        "nothing; wait for its result. Then say thank you in a few words and go on to step 5. If "
        "the result says the vitals are unavailable, say in one short sentence that they will be "
        "taken on the next screen, and go on. Never say the vitals are done unless request_vitals "
        "told you so. Call request_vitals only once."
    )


def _carry_on(known: dict, vitals_taken: bool, language: str) -> str:
    """For a conversation that restarts mid-visit (the page was reloaded,
    or the line to the model dropped): what is already saved."""
    saved = {k: v for k, v in (known or {}).items() if k in INTAKE_FIELDS and v not in (None, "")}
    if not saved and not vitals_taken:
        return ""
    lines = "; ".join(f"{k}: {v}" for k, v in saved.items()) or "nothing yet"
    words = CARRY_ON.get(language, CARRY_ON["en"])
    vitals = " The vitals were already measured: do not call request_vitals again." if vitals_taken else ""
    return f"""

CARRYING ON
This conversation was interrupted and has just restarted with the same patient. \
Already saved: {lines}.{vitals} Never ask for any of these again. Instead of the \
greeting in step 1, say only "{words}" and ask the next question that is still \
missing, in the order above. Do not mention the interruption."""


def system_instruction(
    smart_band: bool,
    language: str = "en",
    known: dict | None = None,
    vitals_taken: bool = False,
    decide_vitals: bool = False,
) -> str:
    greeting = (
        _ASK_LANGUAGE
        if language == "auto"
        else f'Step 1, greeting. Say exactly: "{GREETING.get(language, GREETING["en"])}"'
    )
    return f"""You are Dr. Medora, a warm, calm voice assistant at a hospital kiosk. You collect information before the patient sees a doctor. You are not a doctor: never diagnose, never name a likely condition, never recommend a medicine or dose.

HOW YOU SPEAK
Speak clear, simple {SPEECH[language][0] if language in SPEECH else "English or Malayalam, whichever the patient chose,"} at an unhurried pace, in short sentences a tired \
or unwell person can follow. Keep each reply to one or two sentences.
The patient is already inside a hospital and about to see a doctor, so never \
tell them to consult a healthcare professional, and never say that this is \
not medical advice or not a diagnosis. Do not add any closing disclaimer.

ONE QUESTION AT A TIME
Every reply asks exactly ONE question, then stops and listens. Never put two \
questions in one reply, and never join two questions with "and" or "or".
Wrong: "How long have you had the fever? Do you have any allergies?"
Wrong: "Do you smoke, and do you drink alcohol?"
Right: "How long have you had the fever?" Then wait, and ask about allergies \
in a later reply.
An acknowledgement is a statement, not a question: "I see, a fever with \
chills.", never "a fever, isn't it?"
Match each answer to the one question you asked. If an answer is unclear or \
does not answer that question (for example a bare "no" when you asked how \
long), ask the same question again in simpler words before moving on. Never \
save one answer into two fields, and never skip a question because an answer \
to a different question seemed to cover it. Save "none" for something only \
when the patient said they have none; never save a field you did not ask about.

THE CONVERSATION, IN THIS ORDER
{greeting}

Step 2, age and gender, before anything else. Once the patient has told you their problem, say one short kind sentence about it and ask their age. In your next reply ask whether they are male or female. These two come first because they decide which questions matter. Always ask gender: never guess it from the name or the voice. Straight after the gender answer, ask the pregnancy question if the rules below say so.

Step 3, the complaint. This is the most important part. Ask follow-up questions about what the patient told you, and let each answer decide the next question, suited to their age and gender. Ask at least three before moving on, drawn from what is still unknown about THIS complaint: exactly where it is, how bad it is, when and how it started, whether it is constant or comes and goes, what makes it better or worse, and any other symptoms that commonly go with it. Then ask how long it has been going on, as a question of its own, unless they already said. Then, as a separate question, whether they have taken any medicine for it, unless they already said. Then ALWAYS ask, as a question of its own, whether they are allergic to any medicine or injection (or anything else), because the doctor must not give them something they react to. Ask it once; if they answered, do not ask again. Then ask, once, whether they have any long-term condition such as diabetes, high blood pressure or asthma; then, as another question, whether they take any medicine every day. For a child under 12, ask the child's weight (for the dose). For anyone aged 18 or over, ask the habit questions below. Never ask for something the patient has already told you, and never ask an unrelated or generic question. Do not ask for name or phone number during this step.

PREGNANCY, ONLY WHEN IT MATTERS
Ask "Are you pregnant, or is there any chance you could be?" once, gently, as a reply of its own with no other question in it. Ask it ONLY in step 2, straight after the patient has told you their gender, and ONLY when ALL of these are true: the patient said she is female, she is of child-bearing age (about 12 to 50), and her complaint is one where pregnancy changes what the doctor does: pain in the lower abdomen or pelvis, a late or missed period, bleeding from the vagina, nausea or vomiting in the morning, breast tenderness, fainting or dizziness with any of these, or she mentions pregnancy herself. In every other case, never ask it and never mention pregnancy: not for a cough, cold, fever, headache, body pain, skin, eye, ear, joint or chest complaint, not for a man, and not while you do not yet know the patient is a woman. If she was asked, save her answer with update_intake as pregnancy: yes, no or unsure.

HABITS, ADULTS ONLY (18 and over, men and women alike)
Ask "Do you smoke or use tobacco?" as a reply of its own, then "Do you drink alcohol?" as another reply of its own (if they say yes, ask how much or how often), and save both answers together with update_intake as habits, for example "smokes 10 cigarettes a day, drinks alcohol at weekends" or "none". Ask them once. Never ask children these questions.

{_vitals_step(smart_band, decide_vitals)}

Step 5, name and phone. Ask for their full name, then, in the next reply, their phone number. Repeat the phone number back digit by digit and ask if it is right. Email is optional; do not ask for it unless offered.

Step 6, finish. Tell the patient their details will now appear on the screen to check, then call finish_intake.

SAVING WHAT YOU HEAR
Each time you learn or correct a detail, call update_intake straight away with only the fields that changed. For symptoms, always pass the complete list so far, including what you learned from the follow-up questions, not only the newest part, written as short items separated by commas, one symptom per item with its details beside it (for example "fever, worse at night, body pain, headache"), never joined with "and".

EMERGENCIES
If the patient describes something like chest pain with breathlessness, breathlessness at rest, heavy bleeding, fainting, or signs of a stroke, tell them to alert the hospital staff immediately, then continue. Mild breathlessness only on exertion (climbing stairs) is not an emergency: just note it.""" + _language_rules(language) + _carry_on(
        known or {}, vitals_taken, language
    )


def tool_declarations(decide_vitals: bool = False) -> list[dict]:
    """`decide_vitals`: offer vitals_needed (vitals only when the complaint
    calls for them); without it vitals are always taken."""
    tools = [
        {
            "name": "update_intake",
            "description": "Save patient details as soon as they are heard or corrected.",
            "parameters_json_schema": {
                "type": "object",
                "properties": {
                    key: {"type": kind, "description": text}
                    for key, (kind, text) in INTAKE_FIELDS.items()
                },
            },
        },
        {
            "name": "set_language",
            "description": "Record which language the patient is comfortable with; the kiosk screen follows it.",
            "parameters_json_schema": {
                "type": "object",
                "properties": {"language": {"type": "string", "enum": ["en", "ml"]}},
                "required": ["language"],
            },
        },
        {
            "name": "request_vitals",
            "description": "Ask the kiosk to measure the patient's vitals with the band.",
            "parameters_json_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "finish_intake",
            "description": "End the conversation and show the review screen.",
            "parameters_json_schema": {"type": "object", "properties": {}},
        },
    ]
    if decide_vitals:
        tools.append({
            "name": "vitals_needed",
            "description": "Ask whether this patient's complaint needs vitals at all. Call it before request_vitals.",
            "parameters_json_schema": {"type": "object", "properties": {}},
        })
    return tools


# A footer the service sometimes appends to health answers. Medora is told
# not to add disclaimers (the patient is already in a hospital), and the
# kiosk must not show one.
_FOOTER = re.compile(r"\*?\s*Factual answers to health queries[^*\n]*\*?", re.I)


def clean_transcript(text: str) -> str:
    """Medora's words without the service's disclaimer footer."""
    return _FOOTER.sub("", text)


# Sent to the model when staff resume a paused conversation. No "welcome
# back" (the user's request of 2026-10-29): just the question again.
RESUMED = (
    "(The kiosk was paused for a moment and is now resumed. Do not greet the patient, do not "
    "say welcome back and do not mention the pause: just ask your last question again, briefly, "
    "in the patient's language. If you had not asked one yet, ask the next question.)"
)


def clean_intake(args: dict) -> dict:
    """Keeps only known fields with usable values."""
    fields: dict = {}
    for key, value in (args or {}).items():
        if key not in INTAKE_FIELDS or value in (None, ""):
            continue
        if key == "age":
            try:
                age = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= age <= 120:
                fields[key] = age
        elif key == "gender":
            gender = str(value).strip().lower()
            if gender in ("male", "female", "other"):
                fields[key] = gender
        elif key == "weight_kg":
            try:
                weight = float(value)
            except (TypeError, ValueError):
                continue
            if 0 < weight <= 400:
                fields[key] = weight
        elif key == "pregnancy":
            answer = str(value).strip().lower()
            if answer in ("yes", "no", "unsure"):
                fields[key] = answer
        else:
            fields[key] = str(value).strip()
    return fields


class _LineDropped(Exception):
    """The line to the model closed in the middle of the conversation."""


class GeminiLiveProvider:
    """Online voice through the Gemini Live API.

    Active once MEDORA_GEMINI_API_KEY is set. When the service drops the
    line part way (it has closed sessions with "1008 The operation was
    aborted"), a new line is opened up to `RECONNECTS` times with what was
    heard so far, and Medora carries on with the next question; the patient
    only notices a short pause.
    """

    RECONNECTS = 2

    def __init__(self, api_key: str, model: str, voice: str):
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self.name = f"gemini-live:{model}"

    def _config(self, ctx: VoiceContext, tools: "IntakeTools", restarted: bool):
        from google.genai import types

        decide = ctx.vitals_check is not None
        known = dict(tools.heard) if restarted else dict(ctx.known)
        taken = ctx.vitals_taken or (restarted and tools.vitals_done)
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system_instruction(ctx.smart_band, ctx.language, known, taken, decide),
            tools=[{"function_declarations": tool_declarations(decide)}],
            speech_config=types.SpeechConfig(
                # "auto": no fixed language, so Medora can speak both in her
                # greeting and follow the patient's choice.
                language_code=SPEECH[ctx.language][1] if ctx.language in SPEECH else None,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice)
                ),
            ),
            # The patient speaks English or Malayalam: without this hint the
            # transcription guessed Hindi for Malayalam speech.
            input_audio_transcription=types.AudioTranscriptionConfig(language_codes=TRANSCRIBE_LANGUAGES),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def run(self, ctx, inbound, emit) -> None:
        import asyncio

        from google import genai

        client = genai.Client(api_key=self._api_key)
        tools = IntakeTools(ctx, emit)
        # The browser's messages, read once for the whole conversation so a
        # new line to the model can pick up where the old one stopped.
        queue: asyncio.Queue = asyncio.Queue()

        async def pump() -> None:
            async for item in inbound:
                await queue.put(item)
            await queue.put(None)  # the browser has gone

        reader = asyncio.create_task(pump())
        try:
            attempt = 0
            while True:
                try:
                    await self._session(client, ctx, tools, queue, emit, restarted=attempt > 0)
                    return
                except _LineDropped as dropped:
                    attempt += 1
                    if attempt > self.RECONNECTS or tools.finishing:
                        raise RuntimeError(f"The voice line dropped: {dropped}") from dropped
                    log.warning("Voice line dropped (%s); reconnecting (%d)", dropped, attempt)
                    tools.drop_pending()
                    await asyncio.sleep(0.5)
        finally:
            reader.cancel()

    async def _session(self, client, ctx, tools, queue, emit, restarted: bool) -> None:
        import asyncio

        from google.genai import types

        try:
            connection = client.aio.live.connect(model=self._model, config=self._config(ctx, tools, restarted))
            session = await connection.__aenter__()
        except Exception as e:  # noqa: BLE001 - a failed reconnect is a dropped line too
            if restarted:
                raise _LineDropped(f"{type(e).__name__}: {e}") from e
            raise
        cancelled: set[str] = set()
        try:
            if not restarted:
                await emit({"type": "ready"})
            # Makes Medora speak first instead of waiting for the patient.
            if not restarted:
                opening = "A patient has just walked up to the kiosk."
            elif tools.heard:
                opening = "The line dropped for a moment and is back; carry on with the same patient."
            else:  # nothing saved yet: their problem may not have been heard
                opening = ("The line dropped for a moment and is back. Do not greet again: ask the "
                           "patient, briefly, to tell you again how you can help.")
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": opening}]},
                turn_complete=True,
            )

            async def respond(call_id, name, result: dict):
                if call_id in cancelled:
                    return  # answering a cancelled call closes the session
                await session.send_tool_response(
                    function_responses=[types.FunctionResponse(id=call_id, name=name, response=result)]
                )

            async def uplink() -> None:
                while True:
                    item = await queue.get()
                    if item is None:
                        return
                    if isinstance(item, bytes):
                        await session.send_realtime_input(
                            audio=types.Blob(data=item, mime_type="audio/pcm;rate=16000")
                        )
                    elif item.get("type") == "vitals":
                        answer = tools.vitals_measured(item)
                        if answer is None:
                            continue
                        call_id, result = answer
                        if call_id is None:
                            # Its call is gone (new line, or cancelled): tell the model.
                            await session.send_client_content(
                                turns={"role": "user", "parts": [{"text": f"(The band measurement has finished. {result['result']})"}]},
                                turn_complete=True,
                            )
                        else:
                            await respond(call_id, "request_vitals", result)
                    elif item.get("type") == "pause":
                        # The microphone stops; let the model close the turn
                        # it was hearing rather than wait for more speech.
                        try:
                            await session.send_realtime_input(audio_stream_end=True)
                        except Exception:
                            pass
                    elif item.get("type") == "resume":
                        await session.send_client_content(
                            turns={"role": "user", "parts": [{"text": RESUMED}]},
                            turn_complete=True,
                        )

            async def downlink() -> None:
                while True:
                    got = False
                    # receive() yields one model turn, then ends.
                    async for message in session.receive():
                        got = True
                        if message.data:
                            await emit(message.data)
                        if message.tool_call_cancellation and message.tool_call_cancellation.ids:
                            ids = set(message.tool_call_cancellation.ids)
                            cancelled.update(ids)
                            if tools.pending_vitals_id in ids:
                                tools.drop_pending()
                        content = message.server_content
                        if content:
                            if content.interrupted:
                                await emit({"type": "interrupted"})
                            for role, part in (
                                ("patient", content.input_transcription),
                                ("medora", content.output_transcription),
                            ):
                                if part and part.text:
                                    text = clean_transcript(part.text) if role == "medora" else part.text
                                    if text:
                                        await emit({"type": "transcript", "role": role, "text": text})
                            if content.turn_complete:
                                await emit({"type": "turn_complete"})
                                if tools.finishing:
                                    await emit({"type": "complete"})
                                    return
                        for call in (message.tool_call.function_calls if message.tool_call else []):
                            result = await tools.call(call.id, call.name, dict(call.args or {}))
                            if result is not None:
                                await respond(call.id, call.name, result)
                    if not got:
                        # The service closed the line without an error.
                        raise _LineDropped("the service closed the session")

            up = asyncio.create_task(uplink())
            down = asyncio.create_task(downlink())
            try:
                done, _ = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    error = task.exception()
                    if error is None:
                        continue
                    if isinstance(error, _LineDropped):
                        raise error
                    # Anything from the model's side mid-conversation (1008,
                    # a closed socket) is a dropped line.
                    raise _LineDropped(f"{type(error).__name__}: {error}") from error
            finally:
                up.cancel()
                down.cancel()
        finally:
            try:
                await connection.__aexit__(None, None, None)
            except Exception:
                pass


def make_voice_provider(settings: Settings) -> VoiceProvider | None:
    """The provider to use, or None when voice cannot run on this server.

    SLOT: the offline pipeline (Whisper -> local model -> Piper) plugs in here
    as a second VoiceProvider for when Gemini cannot be reached.
    """
    if settings.gemini_api_key:
        return GeminiLiveProvider(
            settings.gemini_api_key, settings.gemini_live_model, settings.gemini_voice
        )
    return None


VOICE_UNAVAILABLE = "The voice agent is not set up on this server yet."
VOICE_NEEDS_INTERNET = "The voice agent needs an internet connection."


def pick_provider(state) -> tuple[VoiceProvider | None, str]:
    """The provider to use right now, or None with the reason there is none.

    Online, the Gemini provider is used. Without internet the offline
    provider takes over, once one is installed (`offline_voice_provider`).
    """
    if state.voice_provider is not None and state.runtime.online:
        return state.voice_provider, ""
    if state.offline_voice_provider is not None:
        return state.offline_voice_provider, ""
    if state.voice_provider is not None:
        return None, VOICE_NEEDS_INTERNET
    return None, VOICE_UNAVAILABLE


def voice_capability(state) -> tuple[bool, str]:
    provider, reason = pick_provider(state)
    return (True, provider.name) if provider else (False, reason)
