from datetime import date
from uuid import UUID, uuid4

import pytest

from app.exceptions import (
    AssistantEmptyResponse,
    AssistantRateLimited,
    AssistantUnavailable,
    ConversationNotFound,
    DatabaseError,
)
from app.main import app
from app.models.availability import AvailableRoom
from app.models.chat import (
    AvailabilityChatResponse,
    SlotCollectionChatResponse,
    TextChatResponse,
)
from app.models.slots import Slots
from app.services.chat_service import get_chat_service

CONVERSATION_ID = "6f0c1a3e-8b1d-4c53-9d1a-2f7e5b9c4a10"


class FakeChatService:
    def __init__(self):
        self.response = TextChatResponse(message="The hotel has a swimming pool.")
        self.error: Exception | None = None
        self.calls: list[tuple[UUID, str]] = []

    def handle(self, conversation_id, message):
        self.calls.append((conversation_id, message))
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def service():
    fake = FakeChatService()
    app.dependency_overrides[get_chat_service] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def post(client, message="Do you have a swimming pool?", conversation_id=CONVERSATION_ID):
    return client.post("/api/v1/chat", json={"conversation_id": conversation_id, "message": message})


# --- successful replies --------------------------------------------------------------------------


def test_text_reply_matches_the_guide_example(client, service):
    response = post(client)

    assert response.status_code == 200
    assert response.json() == {
        "response_type": "text",
        "message": "The hotel has a swimming pool.",
    }


def test_the_message_and_conversation_reach_the_service(client, service):
    post(client, message="  Do you have a gym?  ")

    assert service.calls == [(UUID(CONVERSATION_ID), "Do you have a gym?")]


def test_slot_collection_reply(client, service):
    service.response = SlotCollectionChatResponse(
        message="Please provide check-out date.",
        missing_fields=["check_out"],
        slots=Slots(check_in=date(2026, 10, 21)),
    )

    body = post(client, "Do you have rooms available?").json()

    assert body["response_type"] == "slot_collection"
    assert body["missing_fields"] == ["check_out"]
    assert body["slots"]["check_in"] == "2026-10-21"


def test_availability_reply(client, service):
    service.response = AvailabilityChatResponse(
        message="Good news!",
        check_in=date(2026, 10, 21),
        check_out=date(2026, 10, 23),
        guest_count=3,
        nights=2,
        rooms=[
            AvailableRoom(
                room_type_id=uuid4(),
                name="Family Suite",
                max_guests=4,
                price_per_night=8500,
                total_price=17000,
                breakfast_included=True,
                rooms_available=3,
            )
        ],
    )

    body = post(client, "Room 21 Oct to 23 Oct for 3").json()

    assert body["response_type"] == "availability"
    assert body["rooms"][0]["name"] == "Family Suite"
    assert body["rooms"][0]["total_price"] == 17000


# --- failures: matching HTTP status, one `error` body shape --------------------------------------


@pytest.mark.parametrize(
    "error,status,code",
    [
        (ConversationNotFound(), 404, "conversation_not_found"),
        (AssistantUnavailable(), 503, "assistant_unavailable"),
        (AssistantRateLimited(), 429, "assistant_busy"),
        (AssistantEmptyResponse(), 502, "assistant_no_answer"),
        (DatabaseError(), 503, "database_unavailable"),
    ],
)
def test_expected_failures_use_their_status_and_the_error_body(client, service, error, status, code):
    service.error = error

    response = post(client)

    assert response.status_code == status
    assert response.json() == {"response_type": "error", "message": error.message, "code": code}


def test_unexpected_errors_become_a_generic_error_body(client, service):
    service.error = RuntimeError("secret internal detail: db password")

    response = post(client)

    assert response.status_code == 500
    body = response.json()
    assert body["response_type"] == "error"
    assert body["code"] == "internal_error"
    assert "secret" not in response.text and "password" not in response.text


# --- bad requests --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"conversation_id": CONVERSATION_ID, "message": "   "},
        {"conversation_id": CONVERSATION_ID, "message": "x" * 1001},
        {"conversation_id": "not-a-uuid", "message": "hi"},
        {"message": "hi"},
        {"conversation_id": CONVERSATION_ID},
    ],
)
def test_invalid_requests_are_rejected_without_calling_the_service(client, service, payload):
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "invalid_request"
    assert service.calls == []


def test_missing_body_is_rejected(client, service):
    response = client.post("/api/v1/chat")

    assert response.status_code == 422
    assert service.calls == []


def test_get_is_not_allowed(client, service):
    assert client.get("/api/v1/chat").status_code == 405


def test_frontend_origin_may_call_chat(client, service):
    response = client.options(
        "/api/v1/chat",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
