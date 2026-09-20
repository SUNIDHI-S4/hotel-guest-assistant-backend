"""The in-memory database is test infrastructure with real logic, so it gets checked too."""

import httpx
import pytest

from tests.fake_supabase import DELUXE_ID, FAMILY_ID, FakeSupabase


@pytest.fixture
def db():
    return FakeSupabase()


def select(db, table, build=lambda q: q):
    return build(db.table(table).select("*")).execute().data


def test_it_is_seeded_with_the_sql_seed_data(db):
    assert [r["name"] for r in select(db, "hotels")] == ["Ocean View Resort"]
    assert len(select(db, "amenities")) == 6
    assert len(select(db, "policies")) == 4
    assert len(select(db, "room_types")) == 3
    assert len(select(db, "bookings")) == 4
    assert select(db, "conversations") == []


def test_filters_are_applied(db):
    assert [r["name"] for r in select(db, "room_types", lambda q: q.gte("max_guests", 4))] == [
        "Family Suite",
        "Executive Suite",
    ]
    assert len(select(db, "bookings", lambda q: q.eq("room_type_id", FAMILY_ID))) == 2
    assert len(select(db, "bookings", lambda q: q.neq("room_type_id", FAMILY_ID))) == 2
    overlapping = select(db, "bookings", lambda q: q.lt("check_in_date", "2026-10-23").gt("check_out_date", "2026-10-21"))
    assert {b["room_type_id"] for b in overlapping} == {FAMILY_ID}


def test_ordering_limit_and_projection(db):
    names = [r["name"] for r in select(db, "amenities", lambda q: q.order("name"))]
    assert names == sorted(names)
    assert [r["name"] for r in select(db, "amenities", lambda q: q.order("name", desc=True).limit(2))] == names[:-3:-1]

    rooms = select(db, "room_types", lambda q: q.order("max_guests", desc=True).order("price_per_night"))
    assert [r["max_guests"] for r in rooms] == [5, 4, 2]

    only_ids = db.table("room_types").select("id").limit(1).execute().data
    assert list(only_ids[0]) == ["id"]


def test_insert_assigns_an_id_and_increasing_timestamps(db):
    first = db.table("conversations").insert({"hotel_id": "h"}).execute().data[0]
    second = db.table("conversations").insert({"hotel_id": "h"}).execute().data[0]

    assert first["id"] != second["id"]
    assert first["created_at"] < second["created_at"]
    assert db.count("conversations") == 2


def test_upsert_updates_the_row_with_the_same_key_instead_of_adding_one(db):
    state = {"conversation_id": "c1", "check_in": "2026-10-21", "check_out": None, "guest_count": None}
    db.table("conversation_state").upsert(state, on_conflict="conversation_id").execute()
    db.table("conversation_state").upsert({**state, "guest_count": 3}, on_conflict="conversation_id").execute()

    rows = select(db, "conversation_state")
    assert len(rows) == 1 and rows[0]["guest_count"] == 3


def test_results_are_copies(db):
    row = select(db, "hotels")[0]
    row["name"] = "Changed"

    assert select(db, "hotels")[0]["name"] == "Ocean View Resort"


def test_a_failure_can_be_injected_once_then_recovers(db):
    db.fail_next(httpx.ConnectError("blip"))

    with pytest.raises(httpx.ConnectError):
        select(db, "hotels")
    assert select(db, "hotels")  # next call works


def test_an_outage_lasts_until_the_test_ends(db):
    db.go_down(httpx.ConnectError("down"))

    for _ in range(3):
        with pytest.raises(httpx.ConnectError):
            select(db, "hotels")


def test_queries_are_logged_in_order(db):
    select(db, "hotels")
    db.table("conversations").insert({"hotel_id": "h"}).execute()

    assert db.queries == [("hotels", "select"), ("conversations", "insert")]
    assert DELUXE_ID  # seed ids are exported for the scenario tests
