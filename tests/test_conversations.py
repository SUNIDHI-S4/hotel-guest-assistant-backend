from uuid import UUID

import pytest

from app.config import get_settings
from app.exceptions import DatabaseError
from app.main import app
from app.repositories.conversation_repository import get_conversation_repository

CONVERSATION_ID = "6f0c1a3e-8b1d-4c53-9d1a-2f7e5b9c4a10"


class FakeConversationRepository:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.created_for: list[str] = []

    def create(self, hotel_id: str) -> str:
        if self.error:
            raise self.error
        self.created_for.append(hotel_id)
        return CONVERSATION_ID


@pytest.fixture
def repository():
    fake = FakeConversationRepository()
    app.dependency_overrides[get_conversation_repository] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def test_create_conversation_returns_id(client, repository):
    response = client.post("/api/v1/conversations")

    assert response.status_code == 201
    body = response.json()
    assert body == {"success": True, "data": {"conversation_id": CONVERSATION_ID}}
    UUID(body["data"]["conversation_id"])


def test_create_conversation_uses_default_hotel(client, repository):
    client.post("/api/v1/conversations")

    assert repository.created_for == [get_settings().default_hotel_id]


def test_database_failure_returns_structured_error(client, repository):
    repository.error = DatabaseError()

    response = client.post("/api/v1/conversations")

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "database_unavailable"
    assert body["error"]["message"]
