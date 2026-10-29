"""Text LLM access for report generation: Gemini online, Ollama offline.

Online the report runs on Gemini. Offline (`main.py` picks by
`runtime.online`) it runs on a local medical model through Ollama
(`offline_model`, MedGemma), which goes through the same pipeline, review
and code rules. A local model that is not a clinical one (`clinical=False`,
the small fallback summariser) is never trusted with conditions or
medicines: see `clinical()`.
"""

import asyncio
import json
import logging
from typing import Protocol

import httpx

from .settings import Settings


log = logging.getLogger("medora.llm")

# Gemini's free tier refuses bursts ("429 RESOURCE_EXHAUSTED") and is
# sometimes briefly overloaded ("503 UNAVAILABLE"); both pass within seconds.
RETRY_WAITS = (2.0, 6.0, 15.0)
# The longest one hosted call may take. A report's calls usually answer in
# 5-30 s; without a limit, one stuck connection held a report for 1 h 47 min
# (2026-10-28). A call that runs out of time is tried once more.
CALL_TIMEOUT = 120.0


def is_transient(error: BaseException) -> bool:
    text = str(error)
    return any(code in text for code in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "overloaded", "rate limit", "Rate limit"))


async def with_retries(call, what: str, timeout: float | None = CALL_TIMEOUT):
    """Runs `call()` again after a short wait when the failure is transient.
    Each attempt gets at most `timeout` seconds; a second time-out ends it."""
    timed_out = 0
    for wait in (*RETRY_WAITS, None):
        try:
            if timeout is None:
                return await call()
            return await asyncio.wait_for(call(), timeout)
        except TimeoutError as e:
            timed_out += 1
            if timed_out > 1 or wait is None:
                raise TimeoutError(f"{what} did not answer within {timeout:.0f} s") from e
            log.warning("%s did not answer within %.0f s; trying once more", what, timeout)
        except Exception as e:
            if wait is None or not is_transient(e):
                raise
            log.warning("%s was refused for now (%s); retrying in %.0f s", what, str(e)[:120], wait)
            await asyncio.sleep(wait)


class LlmError(Exception):
    pass


class Llm(Protocol):
    name: str
    # Trusted to name conditions and medicines (still under review and the
    # rules in code). False for a small general model.
    clinical: bool

    async def json(
        self, system: str, user: str, thinking: int | None = None,
        answer_tokens: int | None = None, schema: dict | None = None,
    ) -> dict:
        """`thinking` caps a hosted model's reasoning tokens (0 = none);
        None leaves the model's default. Less thinking answers sooner.
        `answer_tokens` caps the local model's answer (a short verdict needs
        a few hundred) and `schema` (a JSON schema) makes it fill in exactly
        that form, so it cannot ramble or break the JSON; hosted models
        ignore both."""
        ...


def clinical(llm) -> bool:
    """Whether the model that gave the last answer may write conditions and
    medicines."""
    flag = getattr(llm, "clinical", None)
    if flag is None:  # a model that does not say: only a hosted one is trusted
        return not getattr(llm, "name", "").startswith("ollama")
    return bool(flag)


def _parse(text: str) -> dict:
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as e:
        raise LlmError("The model did not return valid JSON") from e
    if not isinstance(data, dict):
        raise LlmError("The model did not return a JSON object")
    return data


MAX_ANSWER_TOKENS = 1800


class OllamaLlm:
    # Ollama answers one call at a time per model. Calls sent side by side
    # would wait in its queue with their timeout running (a whole offline
    # report once timed out that way), so they take turns here instead.
    _turns: dict[str, asyncio.Lock] = {}

    def __init__(self, url: str, model: str, clinical: bool = False, context: int = 8192, threads: int = 0):
        self._url = url.rstrip("/")
        self._model = model
        self._context = context
        # CPU threads for the model (0 = Ollama's choice). On the i7-1355U
        # laptop, 10 read the prompt twice as fast as the default.
        self._threads = threads
        self.clinical = clinical
        self.name = f"ollama:{model}"

    async def json(
        self, system: str, user: str, thinking: int | None = None,
        answer_tokens: int | None = None, schema: dict | None = None,
    ) -> dict:
        # A cap on the answer's length: in JSON mode a small model can go on
        # writing (whitespace, repeated items) until its context is full,
        # about 20 minutes on a laptop CPU; the review once did. The longest
        # real answer (the writer's draft) is under 1,500 tokens.
        options = {"temperature": 0.2, "num_ctx": self._context, "num_predict": answer_tokens or MAX_ANSWER_TOKENS}
        if self._threads:
            options["num_thread"] = self._threads
        turn = self._turns.setdefault(self._model, asyncio.Lock())
        try:
            # CPU-only inference on a small machine can take a while.
            async with turn, httpx.AsyncClient(timeout=900) as client:
                response = await client.post(
                    f"{self._url}/api/chat",
                    json={
                        "model": self._model,
                        "stream": False,
                        "format": schema or "json",
                        # The default context is too short for a case with its
                        # evidence and instructions; the model would see only
                        # the end of it.
                        "options": options,
                        "keep_alive": "30m",
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            raise LlmError(f"Ollama request failed: {e}") from e
        return _parse(response.json().get("message", {}).get("content"))


class GeminiLlm:
    clinical = True

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model
        self.name = f"gemini:{model}"

    async def json(
        self, system: str, user: str, thinking: int | None = None,
        answer_tokens: int | None = None, schema: dict | None = None,
    ) -> dict:
        from google import genai
        from google.genai import types

        # The client's own limit (milliseconds) ends the request itself; the
        # one in with_retries stops the wait.
        client = genai.Client(api_key=self._api_key, http_options=types.HttpOptions(timeout=int(CALL_TIMEOUT * 1000)))
        try:
            response = await with_retries(
                lambda: client.aio.models.generate_content(
                    model=self._model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        temperature=0.2,
                        thinking_config=(
                            None if thinking is None else types.ThinkingConfig(thinking_budget=thinking)
                        ),
                    ),
                ),
                f"Gemini {self._model}",
            )
        except Exception as e:
            raise LlmError(f"Gemini request failed: {e}") from e
        return _parse(response.text)


class FallbackLlm:
    """Tries each model in order; this is the online -> offline switch."""

    def __init__(self, models: list[Llm]):
        self._models = models
        self.name = models[0].name
        self.clinical = clinical(models[0])

    async def json(
        self, system: str, user: str, thinking: int | None = None,
        answer_tokens: int | None = None, schema: dict | None = None,
    ) -> dict:
        error: LlmError | None = None
        for model in self._models:
            try:
                result = await model.json(system, user, thinking, answer_tokens, schema)
                self.name, self.clinical = model.name, clinical(model)
                return result
            except LlmError as e:
                error = e
        raise error or LlmError("No model is configured")


def make_llm(settings: Settings) -> Llm:
    models: list[Llm] = []
    if settings.gemini_api_key:
        models.append(GeminiLlm(settings.gemini_api_key, settings.gemini_text_model))
    models.append(OllamaLlm(settings.ollama_url, settings.ollama_model))
    return FallbackLlm(models)


def make_report_llm(settings: Settings) -> Llm | None:
    """The chain for the final report's writer, check and review: the report
    model, then the main model, then the small local one (which may not write
    clinical content). None when no separate report model is set."""
    report = settings.gemini_report_model.strip()
    if not settings.gemini_api_key or not report or report == settings.gemini_text_model:
        return None
    return FallbackLlm([
        GeminiLlm(settings.gemini_api_key, report),
        GeminiLlm(settings.gemini_api_key, settings.gemini_text_model),
        OllamaLlm(settings.ollama_url, settings.ollama_model),
    ])


def make_offline_llm(settings: Settings) -> Llm | None:
    """The local medical model the whole report runs on without internet,
    or None when none is configured (then only the plain summary is made)."""
    if not settings.offline_model:
        return None
    return OllamaLlm(settings.ollama_url, settings.offline_model, clinical=True, threads=settings.ollama_threads)
