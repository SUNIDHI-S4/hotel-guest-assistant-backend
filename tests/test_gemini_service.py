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


def build(response=None, error=None, model="gemini-3.1-flash-lite"):
    models = FakeModels(response=response, error=error)
    return GeminiService(SimpleNamespace(models=models), model), models


def build_with_fallback(primary_error, fallback_response=None, fallback_error=None, model="gemini-3.1-flash-lite"):
    """A service with two clients, so the fallback-on-rate-limit behaviour can be exercised."""
    primary = FakeModels(error=primary_error)
    fallback = FakeModels(response=fallback_response, error=fallback_error)
    service = GeminiService(
        SimpleNamespace(models=primary), model, fallback_client=SimpleNamespace(models=fallback)
    )
    return service, primary, fallback


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
    assert call["model"] == "gemini-3.1-flash-lite"
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


def test_the_sdk_is_told_no_tools_are_in_play():
    service, models = build(reply("ok"))

    service.generate(PROMPT)

    assert models.calls[0]["config"].automatic_function_calling.disable is True


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


# --- fallback key on quota exhaustion -------------------------------------------------------------


def test_a_rate_limited_primary_key_falls_back_to_the_second_key():
    rate_limited = api_error(errors.ClientError, 429, "RESOURCE_EXHAUSTED")
    service, primary, fallback = build_with_fallback(rate_limited, fallback_response=reply("Yes, we have a spa."))

    assert service.generate(PROMPT) == "Yes, we have a spa."
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1
    assert fallback.calls[0]["model"] == "gemini-3.1-flash-lite"


def test_if_both_keys_are_rate_limited_the_error_is_still_busy_not_unavailable():
    rate_limited = api_error(errors.ClientError, 429, "RESOURCE_EXHAUSTED")
    also_rate_limited = api_error(errors.ClientError, 429, "RESOURCE_EXHAUSTED")
    service, primary, fallback = build_with_fallback(rate_limited, fallback_error=also_rate_limited)

    with pytest.raises(AssistantRateLimited) as raised:
        service.generate(PROMPT)

    assert raised.value.code == "assistant_busy"
    assert len(primary.calls) == 1 and len(fallback.calls) == 1


@pytest.mark.parametrize(
    "primary_error",
    [
        api_error(errors.ServerError, 503, "UNAVAILABLE"),
        httpx.ConnectTimeout("timed out"),
    ],
    ids=["503", "timeout"],
)
def test_a_non_quota_failure_does_not_try_the_fallback_key(primary_error):
    """An outage or network blip would hit the fallback key too, so it isn't worth the latency."""
    service, primary, fallback = build_with_fallback(primary_error, fallback_response=reply("unused"))

    with pytest.raises(AssistantUnavailable):
        service.generate(PROMPT)

    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_an_empty_reply_from_the_primary_key_does_not_try_the_fallback_key():
    primary = FakeModels(response=reply(""))
    fallback = FakeModels(response=reply("Yes, we have a spa."))
    service = GeminiService(
        SimpleNamespace(models=primary), "gemini-3.1-flash-lite", fallback_client=SimpleNamespace(models=fallback)
    )

    with pytest.raises(AssistantEmptyResponse):
        service.generate(PROMPT)

    assert fallback.calls == []


def test_without_a_configured_fallback_a_rate_limit_fails_immediately():
    service, models = build(error=api_error(errors.ClientError, 429, "RESOURCE_EXHAUSTED"))

    with pytest.raises(AssistantRateLimited):
        service.generate(PROMPT)

    assert len(models.calls) == 1


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
    codes = options.retry_options.http_status_codes
    assert {500, 502, 503, 504} <= set(codes)  # transient server errors are retried once
    assert 429 not in codes  # a per-minute rate limit is not: retrying only burns more quota
    assert service._model == "gemini-3.1-flash-lite"
    assert len(service._clients) == 1  # no GEMINI_API_KEY_FALLBACK in the test environment


def test_a_configured_fallback_key_builds_a_second_client(monkeypatch):
    captured = []

    class FakeClient:
        def __init__(self, api_key, http_options):
            captured.append(api_key)

    monkeypatch.setattr(gemini_service.genai, "Client", FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY_FALLBACK", "second-account-key")
    get_gemini_service.cache_clear()
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        service = get_gemini_service()
    finally:
        get_gemini_service.cache_clear()
        get_settings.cache_clear()

    assert captured == ["test-gemini-key", "second-account-key"]
    assert [label for label, _ in service._clients] == ["primary", "fallback"]


def test_an_unset_fallback_key_builds_only_the_primary_client(monkeypatch):
    captured = []

    class FakeClient:
        def __init__(self, api_key, http_options):
            captured.append(api_key)

    monkeypatch.setattr(gemini_service.genai, "Client", FakeClient)
    get_gemini_service.cache_clear()
    try:
        service = get_gemini_service()
    finally:
        get_gemini_service.cache_clear()

    assert captured == ["test-gemini-key"]
    assert [label for label, _ in service._clients] == ["primary"]
