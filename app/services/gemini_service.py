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
# One retry on transient failures (rate limits, overload) with a short pause; more would
# leave a guest staring at a spinner.
RETRY_ATTEMPTS = 2
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]


class GeminiService:
    """Sends a grounded prompt to Gemini and returns the reply text.

    Every failure becomes one of three AppErrors, so callers never see SDK or network
    exceptions: AssistantRateLimited, AssistantEmptyResponse or AssistantUnavailable.
    """

    def __init__(self, client: genai.Client, model: str):
        self._client = client
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
            # Flash can skip its "thinking" step: faster, cheaper, and thinking tokens can
            # otherwise eat the output budget. Other model families don't allow turning it off.
            thinking_config=types.ThinkingConfig(thinking_budget=0) if "flash" in self._model else None,
        )

        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except errors.APIError as exc:
            logger.error("Gemini API error: code=%s status=%s message=%s", exc.code, exc.status, exc.message)
            if exc.code == 429:
                raise AssistantRateLimited() from exc
            raise AssistantUnavailable() from exc
        except Exception as exc:  # timeouts, connection failures, anything the SDK lets through
            logger.exception("Gemini request failed (%s)", type(exc).__name__)
            raise AssistantUnavailable() from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        text = (response.text or "").strip()
        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        usage = response.usage_metadata
        logger.info(
            "Gemini reply: model=%s %dms finish=%s prompt_tokens=%s output_tokens=%s",
            self._model,
            elapsed_ms,
            getattr(finish_reason, "name", finish_reason),
            getattr(usage, "prompt_token_count", None),
            getattr(usage, "candidates_token_count", None),
        )

        if not text:
            block = getattr(response.prompt_feedback, "block_reason", None)
            logger.warning("Gemini returned no text (finish=%s, blocked=%s)", finish_reason, block)
            raise AssistantEmptyResponse()
        return text


@lru_cache
def get_gemini_service() -> GeminiService:
    settings = get_settings()
    client = genai.Client(
        api_key=settings.gemini_api_key,
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
    return GeminiService(client, settings.gemini_model)
