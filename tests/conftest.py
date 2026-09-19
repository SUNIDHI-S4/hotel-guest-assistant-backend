import os

# Dummy config so tests never depend on (or touch) the real .env / Supabase / Gemini.
# Environment variables take priority over .env in pydantic-settings.
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_KEY", "test-supabase-key")
os.environ.setdefault("DEFAULT_HOTEL_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("HOTEL_TIMEZONE", "Asia/Kolkata")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
