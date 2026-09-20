import logging
import re

import httpx
from fastapi.testclient import TestClient
from google.genai import errors

from app.logging_config import REQUEST_ID_HEADER, configure_logging
from app.main import create_app


def request_records(caplog):
    return [r for r in caplog.records if r.name == "app.request"]


# --- request ids ---------------------------------------------------------------------------------


def test_every_response_carries_a_request_id(stack):
    response = stack.client.get("/api/v1/health")

    assert re.fullmatch(r"[0-9a-f]{12}", response.headers[REQUEST_ID_HEADER])


def test_each_request_gets_its_own_id(stack):
    ids = {stack.client.get("/api/v1/health").headers[REQUEST_ID_HEADER] for _ in range(5)}

    assert len(ids) == 5


def test_an_id_supplied_by_the_caller_is_reused(stack):
    response = stack.client.get("/api/v1/health", headers={REQUEST_ID_HEADER: "trace-abc-123"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-abc-123"


def test_errors_carry_the_id_too(stack):
    response = stack.client.get("/api/v1/conversations/not-a-uuid/messages")

    assert response.status_code == 422
    assert REQUEST_ID_HEADER in response.headers


def test_browsers_may_send_and_read_the_id(stack):
    preflight = stack.client.options(
        "/api/v1/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )
    actual = stack.client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})

    assert preflight.status_code == 200
    assert "x-request-id" in preflight.headers["access-control-allow-headers"].lower()
    assert REQUEST_ID_HEADER.lower() in actual.headers["access-control-expose-headers"].lower()


# --- what gets logged ----------------------------------------------------------------------------


def test_each_request_logs_method_path_status_and_duration(stack, caplog):
    caplog.set_level(logging.INFO)

    stack.client.post("/api/v1/conversations")

    (record,) = request_records(caplog)
    assert re.fullmatch(r"POST /api/v1/conversations -> 201 in \d+ms", record.getMessage())
    assert record.levelno == logging.INFO


def test_log_lines_written_while_handling_a_request_carry_its_id(stack, caplog):
    caplog.set_level(logging.INFO)
    cid = stack.conversation()
    caplog.clear()

    response = stack.client.post("/api/v1/chat", json={"conversation_id": cid, "message": "What time is check-in?"})

    request_id = response.headers[REQUEST_ID_HEADER]
    by_logger = {r.name: r for r in caplog.records}
    for name in ("app.services.retrieval_service", "app.services.gemini_service", "app.services.chat_service", "app.request"):
        assert by_logger[name].request_id == request_id, name


def test_the_chat_turn_line_names_the_conversation_and_what_happened(stack, caplog):
    caplog.set_level(logging.INFO)
    cid = stack.conversation()

    stack.chat(cid, "Do you have rooms available?")

    turn = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Chat turn"))
    assert f"conversation={cid}" in turn
    assert "intent=availability" in turn and "response=slot_collection" in turn


def test_the_id_does_not_leak_into_logging_outside_a_request(stack, caplog):
    caplog.set_level(logging.INFO)
    stack.client.get("/api/v1/health")

    logging.getLogger("elsewhere").warning("background work")

    outside = next(r for r in caplog.records if r.name == "elsewhere")
    assert outside.request_id == "-"


def test_client_errors_are_info_and_server_errors_are_warnings(stack, caplog):
    caplog.set_level(logging.INFO)
    caplog.clear()

    stack.client.get("/api/v1/conversations/00000000-0000-4000-8000-000000000001/messages")  # 404
    stack.db.go_down(httpx.ConnectError("down"))
    stack.client.post("/api/v1/conversations")  # 503

    levels = [r.levelno for r in request_records(caplog)]
    assert levels == [logging.INFO, logging.WARNING]


def test_a_crash_is_logged_with_its_traceback():
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logging.getLogger("app.request").addHandler(handler)
    try:
        response = TestClient(app, raise_server_exceptions=False).get("/boom")
    finally:
        logging.getLogger("app.request").removeHandler(handler)

    assert response.status_code == 500
    crash = next(r for r in records if "unhandled error" in r.getMessage())
    assert crash.levelno == logging.ERROR and crash.exc_info is not None


# --- privacy -------------------------------------------------------------------------------------


def test_guest_message_text_never_reaches_the_logs(stack, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "SECRET-PHRASE-7431"
    cid = stack.conversation()

    stack.chat(cid, f"{secret} do you have a swimming pool?")  # answered by Gemini
    stack.chat(cid, f"{secret} room from 21 October to 23 October for 2 guests")  # availability
    stack.gemini.errors = [errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})]
    stack.chat(cid, f"{secret} is there a spa?")  # Gemini failure
    stack.db.go_down(httpx.ConnectError("database down"))
    stack.chat(cid, f"{secret} what time is check-in?")  # database outage

    assert secret not in caplog.text
    assert len(caplog.records) > 10  # the logging really was active


# --- configuration -------------------------------------------------------------------------------


def test_chatty_libraries_are_quieted(stack):
    for name in ("httpx", "httpcore", "google_genai"):
        assert logging.getLogger(name).level == logging.WARNING


def test_configuring_twice_does_not_duplicate_output():
    configure_logging("INFO")
    configure_logging("INFO")

    ours = [h for h in logging.getLogger().handlers if getattr(h, "_hotel_assistant_handler", False)]
    assert len(ours) == 1
