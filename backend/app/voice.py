"""Voice intake conversation.

Wire protocol on `/ws/voice` (the browser never talks to the model directly,
so the API key stays on the server):

  browser -> server
    binary                 microphone audio, PCM16 mono 16 kHz
    {"type": "start", "smartBand": bool, "language": "auto" | "en" | "ml"}
                           "auto": Medora asks which language the patient
                           is comfortable with and answers `language`
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
from dataclasses import dataclass
from typing import Protocol

from .settings import Settings

log = logging.getLogger("medora.voice")

Inbound = bytes | dict
Emit = Callable[[bytes | dict], Awaitable[None]]


@dataclass
class VoiceContext:
    smart_band: bool
    # Decides from the symptoms (and age, if known) whether vitals are
    # needed: (needed, reason). None means always take them.
    vitals_check: Callable[[str, int | None], Awaitable[tuple[bool, str]]] | None = None
    # en | ml: the language Dr. Medora speaks; "auto" until the patient has
    # said which they are comfortable with (set_language).
    language: str = "en"


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
        # What the patient has said so far, for the vitals decision.
        self.heard: dict = {}
        # The answer to the measurement, reused if the model asks again.
        self._vitals_answer: dict | None = None
        # None until decided; then whether vitals are needed.
        self._decision: bool | None = None
        self.pending_vitals_id: str | None = None
        self.finishing = False

    _NO_DEVICE = {"result": "This kiosk has no vitals device. Continue without them."}
    _SKIP = {
        "result": "Vitals are not needed for this complaint. Do not mention vitals "
        "or the band; continue with step 4."
    }

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
            self.finishing = True
            return {"result": "ok"}
        return {"result": "unknown tool"}

    def vitals_measured(self, item: dict) -> tuple[str, dict] | None:
        """The kiosk's answer to request_vitals, as (call id, response)."""
        if self.pending_vitals_id is None:
            return None
        call_id, self.pending_vitals_id = self.pending_vitals_id, None
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
            else {"result": "Vitals are unavailable. Continue without them."}
        )
        self._vitals_answer = {**result, "note": "Vitals were taken once already; do not ask again."}
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
    "medications": ("string", "Medication already taken for this, or 'none'"),
    "allergies": ("string", "Allergies to medicines, injections or anything else, or 'none'"),
    "chronic_conditions": ("string", "Long-term conditions such as diabetes, high blood pressure, asthma, or 'none'"),
    "regular_medicines": ("string", "Medicines taken every day for a long-term condition, or 'none'"),
    "weight_kg": ("number", "Weight in kilograms, when asked"),
    "pregnancy": ("string", "Only if asked: yes, no or unsure"),
    "habits": ("string", "Only if asked (adult men): smoking, tobacco and alcohol, as said, e.g. 'smokes 10 cigarettes a day, drinks at weekends', or 'none'"),
}


# Spoken language and the Live API's language code for each kiosk language.
SPEECH = {"en": ("English", "en-US"), "ml": ("Malayalam", "ml-IN")}
# What the patient's speech is transcribed as (shown on the kiosk screen).
TRANSCRIBE_LANGUAGES = ["en-IN", "ml-IN"]


_ASK_LANGUAGE = """Step 1, greeting and language. Your first words are exactly, \
in English only: "Hi, I'm Dr. Medora. How can I help you today?" Say nothing \
more, and no Malayalam yet. Then listen:
- If the patient answers in Malayalam, call set_language with ml at once and \
carry on ONLY in Malayalam, with the problem they told you.
- If they answer in English and tell you their problem, call set_language \
with en and carry on in English.
- If they only greet you ("hi", "hello") without saying their problem, ask in \
English: "Which language are you comfortable with, English or Malayalam?" \
When they answer, call set_language, then ask in that language how you can help.
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
When you save details with update_intake: write symptoms, duration, \
medications and allergies in Malayalam script, as the patient said them; write \
the name in English letters; phone digits only; gender as male, female or other; \
pregnancy as yes, no or unsure; habits in Malayalam script. The pregnancy \
question in Malayalam: ഇപ്പോൾ ഗർഭിണിയാണോ, അതോ ആകാൻ സാധ്യതയുണ്ടോ? \
The habit questions in Malayalam: പുകവലിക്കുകയോ പുകയില ഉപയോഗിക്കുകയോ ചെയ്യാറുണ്ടോ? \
and: മദ്യപിക്കാറുണ്ടോ?"""


def system_instruction(smart_band: bool, language: str = "en") -> str:
    vitals = (
        "Step 3, vitals. First call vitals_needed, without saying anything about vitals. "
        "If it answers that vitals are not needed, do not mention vitals or the band at all "
        "and go straight to step 4. If they are needed, tell the patient you would like to "
        "take their vitals, ask them to put on the band, and call request_vitals. The kiosk "
        "screen shows them how and starts the measurement when they tap it; it takes about "
        "a minute. Wait for its result. If it reports that vitals are unavailable, say so in "
        "one short sentence and move on. Vitals are taken once: never call request_vitals "
        "a second time."
        if smart_band
        else "Step 3 is skipped: this kiosk has no vitals device. Do not mention vitals."
    )
    return f"""You are Dr. Medora, a warm, calm voice assistant at a hospital kiosk. You collect information before the patient sees a doctor. You are not a doctor: never diagnose, never name a likely condition, never recommend a medicine or dose.

HOW YOU SPEAK
Speak clear, simple {SPEECH[language][0] if language in SPEECH else "English or Malayalam, whichever the patient chose,"} at an unhurried pace, in short sentences a tired \
or unwell person can follow. Keep each reply to one or two sentences.
Ask exactly ONE question per reply, then stop and listen. Never put two \
questions in the same reply, and never join two questions with "and" or "or".
The patient is already inside a hospital and about to see a doctor, so never \
tell them to consult a healthcare professional, and never say that this is \
not medical advice or not a diagnosis. Do not add any closing disclaimer.

THE CONVERSATION, IN THIS ORDER
{_ASK_LANGUAGE if language == "auto" else "Step 1, greeting. Say exactly: \"Hi, I'm Dr. Medora. How can I help you today?\""}

Step 2, the complaint. This is the most important part. Ask follow-up questions about what the patient just told you, and let each answer decide the next question. Ask at least three before moving on, drawn from what is still unknown about THIS complaint: exactly where it is, how bad it is, when and how it started, whether it is constant or comes and goes, what makes it better or worse, and any other symptoms that commonly go with it. Then ask how long it has been going on and whether they have taken any medicine for it, unless they already said. Then ALWAYS ask, as a question of its own, whether they are allergic to any medicine or injection (or anything else), because the doctor must not give them something they react to. Ask it once; if they answered, do not ask again. Then ask, once, whether they have any long-term condition such as diabetes, high blood pressure or asthma, and whether they take any medicine every day for it. For a child under 12, ask the child's weight (for the dose). Never ask for something the patient has already told you, and never ask an unrelated or generic question. Do not ask for name, age or phone number during this step.

PREGNANCY, ONLY WHEN IT MATTERS
Ask "Are you pregnant, or is there any chance you could be?" once, gently, as a reply of its own with no other question in it. Ask it ONLY in step 4, straight after the patient has told you their gender, and ONLY when ALL of these are true: the patient said she is female, she is of child-bearing age (about 12 to 50), and her complaint is one where pregnancy changes what the doctor does: pain in the lower abdomen or pelvis, a late or missed period, bleeding from the vagina, nausea or vomiting in the morning, breast tenderness, fainting or dizziness with any of these, or she mentions pregnancy herself. In every other case, never ask it and never mention pregnancy: not for a cough, cold, fever, headache, body pain, skin, eye, ear, joint or chest complaint, not for a man, and not while you do not yet know the patient is a woman (her gender comes in step 4: ask it then, if it applies). If she was asked, save her answer with update_intake as pregnancy: yes, no or unsure.

{vitals}

Step 4, personal details. Ask for full name, then age, then gender, then phone number, one at a time. Always ask gender: never guess it from the name or the voice. Straight after the gender answer, ask the pregnancy question if the rules above say so, or the habit questions below for a man aged 18 or over.
HABITS, MEN ONLY: once you know the patient is a man aged 18 or over, ask "Do you smoke or use tobacco?" as a reply of its own, then "Do you drink alcohol?" as another reply of its own (if he says yes, how much or how often), and save both answers together with update_intake as habits, for example "smokes 10 cigarettes a day, drinks alcohol at weekends" or "none". Ask them once. Never ask women or children these questions. Repeat the phone number back digit by digit and ask if it is right. Email is optional; do not ask for it unless offered.

Step 5, finish. Tell the patient their details will now appear on the screen to check, then call finish_intake.

SAVING WHAT YOU HEAR
Each time you learn or correct a detail, call update_intake straight away with only the fields that changed. For symptoms, always pass the complete list so far, including what you learned from the follow-up questions, not only the newest part, written as short items separated by commas, one symptom per item with its details beside it (for example "fever, worse at night, body pain, headache"), never joined with "and".

EMERGENCIES
If the patient describes something like chest pain with breathlessness, breathlessness at rest, heavy bleeding, fainting, or signs of a stroke, tell them to alert the hospital staff immediately, then continue. Mild breathlessness only on exertion (climbing stairs) is not an emergency: just note it.""" + _language_rules(language)


def tool_declarations() -> list[dict]:
    return [
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
            "name": "vitals_needed",
            "description": "Ask whether this patient's complaint needs vitals at all. Call it before request_vitals.",
            "parameters_json_schema": {"type": "object", "properties": {}},
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


# A footer the service sometimes appends to health answers. Medora is told
# not to add disclaimers (the patient is already in a hospital), and the
# kiosk must not show one.
_FOOTER = re.compile(r"\*?\s*Factual answers to health queries[^*\n]*\*?", re.I)


def clean_transcript(text: str) -> str:
    """Medora's words without the service's disclaimer footer."""
    return _FOOTER.sub("", text)


# Sent to the model when staff resume a paused conversation.
RESUMED = (
    "(The kiosk was paused for a moment because of noise or an interruption, and "
    "is now resumed. Do not mention the pause at length: say you are back and "
    "repeat your last question briefly, in the patient's language.)"
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


class GeminiLiveProvider:
    """Online voice through the Gemini Live API.

    Active once MEDORA_GEMINI_API_KEY is set.
    """

    def __init__(self, api_key: str, model: str, voice: str):
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self.name = f"gemini-live:{model}"

    async def run(self, ctx, inbound, emit) -> None:
        import asyncio

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system_instruction(ctx.smart_band, ctx.language),
            tools=[{"function_declarations": tool_declarations()}],
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
        async with client.aio.live.connect(model=self._model, config=config) as session:
            await emit({"type": "ready"})
            # Makes Medora speak first instead of waiting for the patient.
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": "A patient has just walked up to the kiosk."}]},
                turn_complete=True,
            )

            tools = IntakeTools(ctx, emit)

            def respond(call_id, name, result: dict):
                return session.send_tool_response(
                    function_responses=[
                        types.FunctionResponse(id=call_id, name=name, response=result)
                    ]
                )

            async def uplink() -> None:
                async for item in inbound:
                    if isinstance(item, bytes):
                        await session.send_realtime_input(
                            audio=types.Blob(data=item, mime_type="audio/pcm;rate=16000")
                        )
                    elif item.get("type") == "vitals":
                        answer = tools.vitals_measured(item)
                        if answer is not None:
                            await respond(answer[0], "request_vitals", answer[1])
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
                    # receive() yields one model turn, then ends.
                    async for message in session.receive():
                        if message.data:
                            await emit(message.data)
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

            up = asyncio.create_task(uplink())
            down = asyncio.create_task(downlink())
            try:
                done, _ = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                up.cancel()
                down.cancel()


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
