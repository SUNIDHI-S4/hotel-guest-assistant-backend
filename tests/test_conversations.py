from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.exceptions import ConversationNotFound, DatabaseError
from app.main import app
from app.models.entities import Message
from app.services.conversation_service import get_conversation_service

CONVERSATION_ID = "6f0c1a3e-8b1d-4c53-9d1a-2f7e5b9c4a10"


def make_message(role, content, second):
    return Message(
        id=uuid4(),
        conversation_id=CONVERSATION_ID,
        role=role,
        content=content,
        created_at=datetime(2026, 9, 19, 10, 0, second),
    )


class FakeConversationService:
    def __init__(self):
        self.error: Exception | None = None
        self.messages: list[Message] = []
        self.requested: list[tuple[UUID, int]] = []

    def create(self) -> str:
        if self.error:
            raise self.error
        return CONVERSATION_ID

    def get_messages(self, conversation_id, limit):
        self.requested.append((conversation_id, limit))
        if self.error:
            raise self.error
        return self.messages


@pytest.fixture
def service():
    fake = FakeConversationService()
    app.dependency_overrides[get_conversation_service] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


# --- POST /conversations -------------------------------------------------------------------------


def test_create_conversation_returns_id(client, service):
    response = client.post("/api/v1/conversations")

    assert response.status_code == 201
    body = response.json()
    assert body == {"success": True, "data": {"conversation_id": CONVERSATION_ID}}
    UUID(body["data"]["conversation_id"])


def test_database_failure_returns_structured_error(client, service):
    service.error = DatabaseError()

    response = client.post("/api/v1/conversations")

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "database_unavailable"
    assert body["error"]["message"]


# --- GET /conversations/{id}/messages ------------------------------------------------------------


def test_history_returns_messages_in_order(client, service):
    service.messages = [
        make_message("user", "Do you have a pool?", 1),
        make_message("assistant", "Yes, an outdoor infinity pool.", 2),
    ]

    response = client.get(f"/api/v1/conversations/{CONVERSATION_ID}/messages")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["conversation_id"] == CONVERSATION_ID
    assert [(m["role"], m["content"]) for m in body["data"]["messages"]] == [
        ("user", "Do you have a pool?"),
        ("assistant", "Yes, an outdoor infinity pool."),
    ]
    first = body["data"]["messages"][0]
    assert set(first) == {"id", "role", "content", "created_at"}
    assert first["created_at"] == "2026-09-19T10:00:01"


def test_history_of_a_new_conversation_is_empty(client, service):
    response = client.get(f"/api/v1/conversations/{CONVERSATION_ID}/messages")

    assert response.status_code == 200
    assert response.json()["data"]["messages"] == []


def test_history_limit_defaults_to_100_and_can_be_changed(client, service):
    client.get(f"/api/v1/conversations/{CONVERSATION_ID}/messages")
    client.get(f"/api/v1/conversations/{CONVERSATION_ID}/messages?limit=20")

    assert service.requested == [(UUID(CONVERSATION_ID), 100), (UUID(CONVERSATION_ID), 20)]


@pytest.mark.parametrize("limit", [0, -1, 201, "many"])
def test_history_rejects_a_bad_limit(client, service, limit):
    response = client.get(f"/api/v1/conversations/{CONVERSATION_ID}/messages?limit={limit}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert service.requested == []


def test_history_of_unknown_conversation_is_a_404(client, service):
    service.error = ConversationNotFound()

    response = client.get(f"/api/v1/conversations/{CONVERSATION_ID}/messages")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "conversation_not_found"
    assert "new chat" in body["error"]["message"]


def test_malformed_conversation_id_uses_the_standard_error_shape(client, service):
    response = client.get("/api/v1/conversations/not-a-uuid/messages")

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "invalid_request"
    assert "conversation_id" in body["error"]["message"]
    assert service.requested == []


def test_history_database_failure_returns_structured_error(client, service):
    service.error = DatabaseError()

    response = client.get(f"/api/v1/conversations/{CONVERSATION_ID}/messages")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
