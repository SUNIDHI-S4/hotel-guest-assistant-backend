import os

# Dummy config so tests never depend on (or touch) the real .env / Supabase / Gemini.
# Environment variables take priority over .env in pydantic-settings.
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_KEY", "test-supabase-key")
os.environ.setdefault("DEFAULT_HOTEL_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("HOTEL_TIMEZONE", "Asia/Kolkata")
# Explicitly empty, not just unset: otherwise a real GEMINI_API_KEY_FALLBACK in .env (there to
# configure the real server) would leak into tests via pydantic-settings' env_file fallback,
# since os.environ has no entry for pydantic-settings to prefer over the .env file with.
os.environ.setdefault("GEMINI_API_KEY_FALLBACK", "")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def stack(monkeypatch):
    """The real app on an in-memory database with a scripted Gemini; see tests/stack.py."""
    from tests.stack import clear_provider_caches, make_stack

    yield make_stack(monkeypatch)
    clear_provider_caches()
