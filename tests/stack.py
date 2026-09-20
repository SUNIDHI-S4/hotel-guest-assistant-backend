"""Test rig: the real application wired to an in-memory database and a scripted Gemini."""

import importlib
import pkgutil
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_package
from app.main import create_app
from tests.fake_supabase import FakeSupabase


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        # 12:00 in India on Saturday 19 September 2026, so the seed bookings are all in the future.
        return datetime(2026, 9, 19, 6, 30, tzinfo=timezone.utc).astimezone(tz)


class FakeGemini:
    """Scripted stand-in for the Gemini SDK client; records every prompt it is sent."""

    def __init__(self):
        self.calls: list[SimpleNamespace] = []
        self.replies: list[str] = []
        self.errors: list[Exception | None] = []
        self.models = self  # the SDK exposes client.models.generate_content

    def generate_content(self, model, contents, config):
        self.calls.append(
            SimpleNamespace(
                model=model,
                system=config.system_instruction,
                turns=[(c.role, c.parts[0].text) for c in contents],
            )
        )
        if self.errors:
            error = self.errors.pop(0)
            if error:
                raise error
        text = self.replies.pop(0) if self.replies else "Fake answer."
        return SimpleNamespace(
            text=text,
            candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
            usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=10),
            prompt_feedback=None,
        )


def clear_provider_caches():
    """Forget every cached service, so each test builds the real object graph from scratch."""
    for module_info in pkgutil.walk_packages(app_package.__path__, "app."):
        module = importlib.import_module(module_info.name)
        for value in vars(module).values():
            if hasattr(value, "cache_clear"):
                value.cache_clear()


class Stack:
    def __init__(self, db: FakeSupabase, gemini: FakeGemini):
        self.db = db
        self.gemini = gemini
        self.restart()

    def restart(self):
        """A fresh application on the same database, as after a server restart."""
        clear_provider_caches()
        self.client = TestClient(create_app())

    def conversation(self) -> str:
        return self.client.post("/api/v1/conversations").json()["data"]["conversation_id"]

    def chat(self, conversation_id, message):
        response = self.client.post(
            "/api/v1/chat", json={"conversation_id": conversation_id, "message": message}
        )
        return response.status_code, response.json()

    def history(self, conversation_id):
        response = self.client.get(f"/api/v1/conversations/{conversation_id}/messages")
        return response.json()["data"]["messages"]

    def knowledge_tables_read(self) -> set[str]:
        tables = {"hotels", "amenities", "policies", "room_types"}
        return {table for table, _ in self.db.queries if table in tables}


def facts_of(call) -> str:
    """The hotel-facts block of the prompt (everything after the rules)."""
    return call.system.split("HOTEL FACTS\n", 1)[1]


def room_summary(body):
    return [(r["name"], r["rooms_available"]) for r in body["rooms"]]


def make_stack(monkeypatch) -> Stack:
    """Patch the clock, retry sleeps, Supabase and Gemini, then build the real app on top."""
    from app.services import gemini_service

    monkeypatch.setattr("app.clock.datetime", FrozenDatetime)
    monkeypatch.setattr("app.repositories.base.time.sleep", lambda _: None)  # no real retry waits
    db, gemini = FakeSupabase(), FakeGemini()
    monkeypatch.setattr("app.db.supabase_client.create_client", lambda url, key: db)
    monkeypatch.setattr(gemini_service.genai, "Client", lambda **kwargs: SimpleNamespace(models=gemini))
    return Stack(db, gemini)
