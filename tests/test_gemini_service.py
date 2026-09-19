from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.exceptions import AssistantEmptyResponse, AssistantRateLimited, AssistantUnavailable
from app.models.prompt import ChatTurn, Prompt
from app.services import gemini_service
from app.services.gemini_service import GeminiService, get_gemini_service

PROMPT = Prompt(
    system_instruction="RULES ... HOTEL FACTS ...",
    turns=[
        ChatTurn(role="user", text="Do you have a gym?"),
        ChatTurn(role="model", text="Yes, a fully equipped fitness center."),
        ChatTurn(role="user", text="And a spa?"),
    ],
)


def reply(text, finish="STOP", block_reason=None):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        usage_metadata=SimpleNamespace(prompt_token_count=120, candidates_token_count=20),
        prompt_feedback=SimpleNamespace(block_reason=block_reason) if block_reason else None,
    )


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return self.response


def build(response=None, error=None, model="gemini-3.6-flash"):
    models = FakeModels(response=response, error=error)
    return GeminiService(SimpleNamespace(models=models), model), models


def api_error(cls, code, status):
    return cls(code, {"error": {"code": code, "message": "boom", "status": status}})


# --- request -------------------------------------------------------------------------------------


def test_returns_the_reply_text_trimmed():
    service, _ = build(reply("  Yes, we have a spa.\n"))

    assert service.generate(PROMPT) == "Yes, we have a spa."


def test_sends_the_conversation_and_rules():
    service, models = build(reply("ok"))

    service.generate(PROMPT)

    (call,) = models.calls
    assert call["model"] == "gemini-3.6-flash"
    assert [(c.role, c.parts[0].text) for c in call["contents"]] == [
        ("user", "Do you have a gym?"),
        ("model", "Yes, a fully equipped fitness center."),
        ("user", "And a spa?"),
    ]
    assert call["config"].system_instruction == PROMPT.system_instruction


def test_generation_settings_favour_grounded_answers():
    service, models = build(reply("ok"))

    service.generate(PROMPT)

    config = models.calls[0]["config"]
    assert config.temperature == gemini_service.TEMPERATURE == 0.2
    assert config.max_output_tokens == gemini_service.MAX_OUTPUT_TOKENS
    assert config.thinking_config.thinking_budget == 0


def test_thinking_is_only_switched_off_for_flash_models():
    service, models = build(reply("ok"), model="gemini-2.5-pro")

    service.generate(PROMPT)

    assert models.calls[0]["config"].thinking_config is None


def test_a_reply_cut_off_by_the_token_limit_is_still_returned():
    service, _ = build(reply("The hotel has a pool, gym and", finish="MAX_TOKENS"))

    assert service.generate(PROMPT) == "The hotel has a pool, gym and"


# --- failures ------------------------------------------------------------------------------------


def test_rate_limit_is_reported_as_busy():
    service, _ = build(error=api_error(errors.ClientError, 429, "RESOURCE_EXHAUSTED"))

    with pytest.raises(AssistantRateLimited) as raised:
        service.generate(PROMPT)

    assert raised.value.status_code == 429
    assert raised.value.code == "assistant_busy"


@pytest.mark.parametrize(
    "error",
    [
        api_error(errors.ServerError, 503, "UNAVAILABLE"),
        api_error(errors.ServerError, 500, "INTERNAL"),
        api_error(errors.ClientError, 400, "INVALID_ARGUMENT"),  # e.g. bad API key or request
        api_error(errors.ClientError, 403, "PERMISSION_DENIED"),
        httpx.ConnectTimeout("timed out"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("refused"),
        ConnectionError("reset"),
        RuntimeError("something inside the SDK"),
    ],
    ids=lambda e: type(e).__name__ + str(getattr(e, "code", "")),
)
def test_any_other_failure_is_reported_as_unavailable(error):
    service, _ = build(error=error)

    with pytest.raises(AssistantUnavailable) as raised:
        service.generate(PROMPT)

    assert raised.value.status_code == 503
    assert raised.value.code == "assistant_unavailable"
    assert raised.value.__cause__ is error  # kept for debugging


@pytest.mark.parametrize(
    "response",
    [
        reply(""),
        reply("   \n"),
        reply(None),
        reply(None, finish="SAFETY"),
        reply(None, finish="OTHER", block_reason="PROHIBITED_CONTENT"),
        SimpleNamespace(text=None, candidates=None, usage_metadata=None, prompt_feedback=None),
    ],
)
def test_empty_or_blocked_replies_raise_no_answer(response):
    service, _ = build(response)

    with pytest.raises(AssistantEmptyResponse) as raised:
        service.generate(PROMPT)

    assert raised.value.status_code == 502
    assert raised.value.code == "assistant_no_answer"
    assert "rephras" in raised.value.message


def test_error_messages_are_safe_to_show_guests():
    for error in (AssistantUnavailable(), AssistantRateLimited(), AssistantEmptyResponse()):
        text = error.message.lower()
        assert not any(word in text for word in ("gemini", "api", "exception", "traceback", "key"))


# --- client setup --------------------------------------------------------------------------------


def test_client_is_configured_from_settings(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, api_key, http_options):
            captured.update(api_key=api_key, http_options=http_options)

    monkeypatch.setattr(gemini_service.genai, "Client", FakeClient)
    get_gemini_service.cache_clear()
    try:
        service = get_gemini_service()
    finally:
        get_gemini_service.cache_clear()

    assert captured["api_key"] == "test-gemini-key"
    options = captured["http_options"]
    assert options.timeout == 15000  # milliseconds
    assert options.retry_options.attempts == gemini_service.RETRY_ATTEMPTS == 2
    assert 429 in options.retry_options.http_status_codes
    assert service._model == "gemini-3.6-flash"
