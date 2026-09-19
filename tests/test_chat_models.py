from datetime import date
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from app.main import create_app
from app.models.availability import AvailabilityResult, AvailableRoom
from app.models.chat import (
    MAX_MESSAGE_LENGTH,
    AvailabilityChatResponse,
    ChatRequest,
    ChatResponse,
    ErrorChatResponse,
    SlotCollectionChatResponse,
    TextChatResponse,
)
from app.models.slots import Slots

CONVERSATION_ID = "6f0c1a3e-8b1d-4c53-9d1a-2f7e5b9c4a10"
ROOM_ID = uuid4()

ROOM = AvailableRoom(
    room_type_id=ROOM_ID,
    name="Family Suite",
    description="Spacious suite suitable for families.",
    max_guests=4,
    price_per_night=8500.0,
    total_price=17000.0,
    breakfast_included=True,
    rooms_available=3,
)

parse_response = TypeAdapter(ChatResponse).validate_python


# --- request -------------------------------------------------------------------------------------


def test_request_accepts_the_guide_example():
    request = ChatRequest(conversation_id=CONVERSATION_ID, message="Do you have a swimming pool?")

    assert str(request.conversation_id) == CONVERSATION_ID
    assert request.message == "Do you have a swimming pool?"


def test_request_trims_surrounding_whitespace():
    request = ChatRequest(conversation_id=CONVERSATION_ID, message="  hello there \n")

    assert request.message == "hello there"


@pytest.mark.parametrize("message", ["", "   ", "\n\t "])
def test_request_rejects_empty_messages(message):
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id=CONVERSATION_ID, message=message)


def test_request_message_length_limit():
    ChatRequest(conversation_id=CONVERSATION_ID, message="a" * MAX_MESSAGE_LENGTH)

    with pytest.raises(ValidationError):
        ChatRequest(conversation_id=CONVERSATION_ID, message="a" * (MAX_MESSAGE_LENGTH + 1))


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "hi"},
        {"conversation_id": CONVERSATION_ID},
        {"conversation_id": "not-a-uuid", "message": "hi"},
        {"conversation_id": CONVERSATION_ID, "message": None},
    ],
)
def test_request_rejects_missing_or_malformed_fields(payload):
    with pytest.raises(ValidationError):
        ChatRequest(**payload)


# --- responses match the guide -------------------------------------------------------------------


def test_text_response_shape():
    response = TextChatResponse(message="The hotel has a swimming pool.")

    assert response.model_dump(mode="json") == {
        "response_type": "text",
        "message": "The hotel has a swimming pool.",
    }


def test_slot_collection_response_shape():
    response = SlotCollectionChatResponse(
        message="Please provide check-out date.",
        missing_fields=["check_out"],
        slots=Slots(check_in=date(2026, 10, 21), guest_count=2),
    )

    assert response.model_dump(mode="json") == {
        "response_type": "slot_collection",
        "message": "Please provide check-out date.",
        "missing_fields": ["check_out"],
        "slots": {"check_in": "2026-10-21", "check_out": None, "guest_count": 2},
    }


def test_availability_response_shape():
    response = AvailabilityChatResponse(
        message="I found available rooms.",
        check_in=date(2026, 10, 21),
        check_out=date(2026, 10, 23),
        guest_count=3,
        nights=2,
        rooms=[ROOM],
    )

    body = response.model_dump(mode="json")

    assert body["response_type"] == "availability"
    assert body["message"] == "I found available rooms."
    assert (body["check_in"], body["check_out"], body["guest_count"], body["nights"]) == (
        "2026-10-21",
        "2026-10-23",
        3,
        2,
    )
    assert body["rooms"] == [
        {
            "room_type_id": str(ROOM_ID),
            "name": "Family Suite",
            "description": "Spacious suite suitable for families.",
            "max_guests": 4,
            "price_per_night": 8500.0,
            "total_price": 17000.0,
            "breakfast_included": True,
            "rooms_available": 3,
        }
    ]


def test_availability_response_can_have_no_rooms():
    response = AvailabilityChatResponse(
        message="Sorry, nothing is free.",
        check_in=date(2026, 10, 21),
        check_out=date(2026, 10, 23),
        guest_count=2,
        nights=2,
        rooms=[],
    )

    assert response.model_dump(mode="json")["rooms"] == []


def test_availability_response_can_be_built_from_the_service_result():
    result = AvailabilityResult(
        check_in=date(2026, 10, 21), check_out=date(2026, 10, 23), guest_count=3, nights=2, rooms=[ROOM]
    )

    response = AvailabilityChatResponse(message="Found rooms.", **result.model_dump())

    assert response.rooms == [ROOM]
    assert response.nights == 2


def test_error_response_shape():
    response = ErrorChatResponse(message="The assistant is unavailable.", code="assistant_unavailable")

    assert response.model_dump(mode="json") == {
        "response_type": "error",
        "message": "The assistant is unavailable.",
        "code": "assistant_unavailable",
    }


# --- validation and the discriminated union ------------------------------------------------------


def test_missing_fields_only_allow_known_slot_names():
    with pytest.raises(ValidationError):
        SlotCollectionChatResponse(message="?", missing_fields=["room_number"], slots=Slots())


@pytest.mark.parametrize(
    "payload,expected_type",
    [
        ({"response_type": "text", "message": "hi"}, TextChatResponse),
        (
            {"response_type": "slot_collection", "message": "?", "missing_fields": [], "slots": {}},
            SlotCollectionChatResponse,
        ),
        (
            {
                "response_type": "availability",
                "message": "ok",
                "check_in": "2026-10-21",
                "check_out": "2026-10-23",
                "guest_count": 2,
                "nights": 2,
                "rooms": [],
            },
            AvailabilityChatResponse,
        ),
        ({"response_type": "error", "message": "oops", "code": "x"}, ErrorChatResponse),
    ],
)
def test_response_type_selects_the_model(payload, expected_type):
    assert isinstance(parse_response(payload), expected_type)


def test_unknown_response_type_is_rejected():
    with pytest.raises(ValidationError):
        parse_response({"response_type": "video", "message": "hi"})


def test_response_type_cannot_be_overridden_on_a_model():
    with pytest.raises(ValidationError):
        TextChatResponse(response_type="error", message="hi")


# --- as a FastAPI response_model -----------------------------------------------------------------


def make_app(response) -> FastAPI:
    app = FastAPI()

    @app.post("/chat", response_model=ChatResponse)
    def chat() -> ChatResponse:
        return response

    return app


@pytest.mark.parametrize(
    "response",
    [
        TextChatResponse(message="hi"),
        SlotCollectionChatResponse(message="?", missing_fields=["check_out"], slots=Slots()),
        AvailabilityChatResponse(
            message="ok",
            check_in=date(2026, 10, 21),
            check_out=date(2026, 10, 23),
            guest_count=3,
            nights=2,
            rooms=[ROOM],
        ),
        ErrorChatResponse(message="oops", code="x"),
    ],
)
def test_fastapi_serialises_every_response_type(response):
    result = TestClient(make_app(response)).post("/chat")

    assert result.status_code == 200
    assert result.json() == response.model_dump(mode="json")


def test_bad_chat_request_uses_the_standard_error_shape():
    app = create_app()

    @app.post("/chat")
    def chat(request: ChatRequest) -> dict:
        return {}

    client = TestClient(app)

    blank = client.post("/chat", json={"conversation_id": CONVERSATION_ID, "message": "   "})
    assert blank.status_code == 422
    assert blank.json()["success"] is False
    assert blank.json()["error"]["code"] == "invalid_request"
    assert "message" in blank.json()["error"]["message"]

    no_body = client.post("/chat")
    assert no_body.status_code == 422
    assert no_body.json()["error"]["code"] == "invalid_request"


def test_openapi_documents_all_four_response_types():
    schemas = make_app(TextChatResponse(message="hi")).openapi()["components"]["schemas"]

    for name in ("TextChatResponse", "SlotCollectionChatResponse", "AvailabilityChatResponse", "ErrorChatResponse"):
        assert name in schemas
