import logging
import time
from functools import lru_cache

from google import genai
from google.genai import errors, types

from app.config import get_settings
from app.exceptions import AssistantEmptyResponse, AssistantRateLimited, AssistantUnavailable
from app.models.prompt import Prompt

logger = logging.getLogger(__name__)

# Low temperature: answers should stick to the facts, not get creative.
TEMPERATURE = 0.2
MAX_OUTPUT_TOKENS = 600
# One retry, with a short pause, for transient server-side failures; more would leave a guest
# staring at a spinner. A 429 (rate limit) is deliberately NOT retried: the quota is per minute,
# so a retry half a second later cannot succeed, and it counts as one more request against the
# quota, keeping it exhausted. It fails fast as "assistant busy" instead.
RETRY_ATTEMPTS = 2
RETRY_STATUS_CODES = [500, 502, 503, 504]


class GeminiService:
    """Sends a grounded prompt to Gemini and returns the reply text.

    Every failure becomes one of three AppErrors, so callers never see SDK or network
    exceptions: AssistantRateLimited, AssistantEmptyResponse or AssistantUnavailable.

    An optional `fallback_client` — a second Gemini key, typically from a different Google
    account/project — is tried only when the primary key comes back rate-limited (its free-tier
    quota is exhausted). A different project has its own separate quota, so this genuinely
    helps. Other failures (a Google-side outage, a bad prompt, a network blip) are not retried
    on the fallback: both keys would hit the same problem, so switching only adds latency.
    """

    def __init__(self, client: genai.Client, model: str, fallback_client: genai.Client | None = None):
        self._clients: list[tuple[str, genai.Client]] = [("primary", client)]
        if fallback_client is not None:
            self._clients.append(("fallback", fallback_client))
        self._model = model

    def generate(self, prompt: Prompt) -> str:
        contents = [
            types.Content(role=turn.role, parts=[types.Part(text=turn.text)])
            for turn in prompt.turns
        ]
        config = types.GenerateContentConfig(
            system_instruction=prompt.system_instruction,
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            # We never give the model tools to call. Saying so keeps the SDK from logging a
            # misleading "automatic function calling" warning at startup.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            # Flash can skip its "thinking" step: faster, cheaper, and thinking tokens can
            # otherwise eat the output budget. Other model families don't allow turning it off.
            thinking_config=types.ThinkingConfig(thinking_budget=0) if "flash" in self._model else None,
        )

        for index, (label, client) in enumerate(self._clients):
            try:
                return self._call(client, label, contents, config)
            except AssistantRateLimited:
                if index == len(self._clients) - 1:
                    raise
                logger.warning(
                    "Gemini key '%s' is rate limited; retrying with the fallback key", label
                )

    def _call(self, client: genai.Client, label: str, contents, config) -> str:
        started = time.perf_counter()
        try:
            response = client.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except errors.APIError as exc:
            logger.error(
                "Gemini API error (key=%s): code=%s status=%s message=%s",
                label, exc.code, exc.status, exc.message,
            )
            if exc.code == 429:
                raise AssistantRateLimited() from exc
            raise AssistantUnavailable() from exc
        except Exception as exc:  # timeouts, connection failures, anything the SDK lets through
            logger.exception("Gemini request failed (key=%s, %s)", label, type(exc).__name__)
            raise AssistantUnavailable() from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        text = (response.text or "").strip()
        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        usage = response.usage_metadata
        logger.info(
            "Gemini reply: key=%s model=%s %dms finish=%s prompt_tokens=%s output_tokens=%s",
            label,
            self._model,
            elapsed_ms,
            getattr(finish_reason, "name", finish_reason),
            getattr(usage, "prompt_token_count", None),
            getattr(usage, "candidates_token_count", None),
        )

        if not text:
            block = getattr(response.prompt_feedback, "block_reason", None)
            logger.warning(
                "Gemini returned no text (key=%s, finish=%s, blocked=%s)", label, finish_reason, block
            )
            raise AssistantEmptyResponse()
        return text


def _build_client(api_key: str, settings) -> genai.Client:
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=int(settings.gemini_timeout_seconds * 1000),
            retry_options=types.HttpRetryOptions(
                attempts=RETRY_ATTEMPTS,
                initial_delay=0.5,
                max_delay=2.0,
                http_status_codes=RETRY_STATUS_CODES,
            ),
        ),
    )


@lru_cache
def get_gemini_service() -> GeminiService:
    settings = get_settings()
    client = _build_client(settings.gemini_api_key, settings)
    fallback_client = (
        _build_client(settings.gemini_api_key_fallback, settings)
        if settings.gemini_api_key_fallback
        else None
    )
    return GeminiService(client, settings.gemini_model, fallback_client)
