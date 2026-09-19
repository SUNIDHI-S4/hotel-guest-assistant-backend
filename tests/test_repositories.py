from datetime import date

import httpx
import pytest
from postgrest.exceptions import APIError

from app.exceptions import DatabaseError
from app.repositories.amenity_repository import AmenityRepository
from app.repositories.base import MAX_ATTEMPTS, execute
from app.repositories.booking_repository import BookingRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.conversation_state_repository import ConversationStateRepository
from app.repositories.hotel_repository import HotelRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.policy_repository import PolicyRepository
from app.repositories.room_type_repository import RoomTypeRepository
from tests.fakes import FakeClient, FakeQuery

HOTEL_ID = "02e96bf4-29ff-484b-8c19-13cbf708402c"
ROOM_ID = "0d788df0-0fce-4a83-9816-1c739be18826"
CONVERSATION_ID = "6f0c1a3e-8b1d-4c53-9d1a-2f7e5b9c4a10"
ROW_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    monkeypatch.setattr("app.repositories.base.time.sleep", lambda _: None)


def repo(cls, rows=None, errors=None):
    query = FakeQuery(rows=rows, errors=errors)
    return cls(FakeClient(query)), query


# --- execute(): retry behaviour ------------------------------------------------------------


def test_execute_retries_transient_error_then_succeeds():
    query = FakeQuery(rows=[1], errors=[httpx.RemoteProtocolError("Server disconnected")])

    assert execute(query).data == [1]
    assert query.executions == 2


def test_execute_gives_up_after_max_attempts():
    errors = [httpx.ConnectError("down")] * MAX_ATTEMPTS
    query = FakeQuery(errors=errors)

    with pytest.raises(DatabaseError):
        execute(query)
    assert query.executions == MAX_ATTEMPTS


def test_execute_does_not_retry_api_errors():
    query = FakeQuery(errors=[APIError({"message": "bad", "code": "42703"})])

    with pytest.raises(DatabaseError):
        execute(query)
    assert query.executions == 1


def test_write_is_not_retried_once_request_may_have_been_sent():
    query = FakeQuery(errors=[httpx.RemoteProtocolError("Server disconnected")])

    with pytest.raises(DatabaseError):
        execute(query, idempotent=False)
    assert query.executions == 1


def test_write_is_retried_when_connection_could_not_be_opened():
    query = FakeQuery(rows=[1], errors=[httpx.ConnectError("refused")])

    assert execute(query, idempotent=False).data == [1]
    assert query.executions == 2


# --- knowledge repositories ----------------------------------------------------------------

HOTEL_ROW = {
    "id": HOTEL_ID,
    "slug": "ocean-view-resort",
    "name": "Ocean View Resort",
    "description": "A resort",
    "address": "123 Beach Road",
    "city": "Goa",
    "state": "Goa",
    "country": "India",
    "check_in_time": "15:00:00",
    "check_out_time": "11:00:00",
    "created_at": "2026-09-19T10:00:00",
}


def test_hotel_get_returns_parsed_hotel():
    hotels, query = repo(HotelRepository, rows=[HOTEL_ROW])

    hotel = hotels.get(HOTEL_ID)

    assert hotel.name == "Ocean View Resort"
    assert hotel.check_in_time.hour == 15
    assert query.calls == [
        ("select", ("*",), {}),
        ("eq", ("id", HOTEL_ID), {}),
        ("limit", (1,), {}),
    ]


def test_hotel_get_returns_none_when_missing():
    hotels, _ = repo(HotelRepository, rows=[])

    assert hotels.get(HOTEL_ID) is None


def test_amenities_are_scoped_to_hotel():
    amenities, query = repo(
        AmenityRepository,
        rows=[{"id": ROW_ID, "hotel_id": HOTEL_ID, "name": "Gym", "description": None}],
    )

    result = amenities.list_for_hotel(HOTEL_ID)

    assert [a.name for a in result] == ["Gym"]
    assert ("eq", ("hotel_id", HOTEL_ID), {}) in query.calls


def test_policies_are_scoped_to_hotel():
    policies, query = repo(
        PolicyRepository,
        rows=[{"id": ROW_ID, "hotel_id": HOTEL_ID, "policy_type": "pets", "content": "No pets."}],
    )

    result = policies.list_for_hotel(HOTEL_ID)

    assert result[0].policy_type == "pets"
    assert ("eq", ("hotel_id", HOTEL_ID), {}) in query.calls


ROOM_ROW = {
    "id": ROOM_ID,
    "hotel_id": HOTEL_ID,
    "name": "Family Suite",
    "description": None,
    "max_guests": 4,
    "price_per_night": 8500.0,
    "breakfast_included": None,
    "total_rooms": 5,
}


def test_room_types_parse_and_treat_null_breakfast_as_false():
    rooms, _ = repo(RoomTypeRepository, rows=[ROOM_ROW])

    room = rooms.list_for_hotel(HOTEL_ID)[0]

    assert room.price_per_night == 8500.0
    assert room.breakfast_included is False


def test_room_types_for_capacity_filter_and_order_smallest_first():
    rooms, query = repo(RoomTypeRepository, rows=[ROOM_ROW])

    rooms.list_for_capacity(HOTEL_ID, 3)

    assert query.calls == [
        ("select", ("*",), {}),
        ("eq", ("hotel_id", HOTEL_ID), {}),
        ("order", ("max_guests",), {}),
        ("order", ("price_per_night",), {}),
        ("gte", ("max_guests", 3), {}),
    ]


def test_booking_overlap_filters():
    bookings, query = repo(
        BookingRepository,
        rows=[
            {
                "id": ROW_ID,
                "hotel_id": HOTEL_ID,
                "room_type_id": ROOM_ID,
                "check_in_date": "2026-10-20",
                "check_out_date": "2026-10-22",
                "guest_count": 3,
                "booking_status": "confirmed",
            }
        ],
    )

    result = bookings.list_overlapping(HOTEL_ID, date(2026, 10, 21), date(2026, 10, 23))

    assert result[0].check_in_date == date(2026, 10, 20)
    # booking.check_in < requested check_out AND booking.check_out > requested check_in
    assert ("lt", ("check_in_date", "2026-10-23"), {}) in query.calls
    assert ("gt", ("check_out_date", "2026-10-21"), {}) in query.calls
    assert ("neq", ("booking_status", "cancelled"), {}) in query.calls
    assert ("eq", ("hotel_id", HOTEL_ID), {}) in query.calls


# --- conversation repositories -------------------------------------------------------------


def test_conversation_create_returns_id_without_blind_retry():
    conversations, query = repo(ConversationRepository, rows=[{"id": CONVERSATION_ID}])

    assert conversations.create(HOTEL_ID) == CONVERSATION_ID
    assert query.calls == [("insert", ({"hotel_id": HOTEL_ID},), {})]


def test_conversation_create_wraps_database_errors():
    conversations, _ = repo(
        ConversationRepository, errors=[APIError({"message": "boom", "code": "500"})]
    )

    with pytest.raises(DatabaseError):
        conversations.create(HOTEL_ID)


@pytest.mark.parametrize("rows,expected", [([{"id": CONVERSATION_ID}], True), ([], False)])
def test_conversation_exists(rows, expected):
    conversations, _ = repo(ConversationRepository, rows=rows)

    assert conversations.exists(CONVERSATION_ID) is expected


def message_row(role, content, created_at):
    return {
        "id": ROW_ID,
        "conversation_id": CONVERSATION_ID,
        "role": role,
        "content": content,
        "created_at": created_at,
    }


def test_message_add_inserts_and_returns_message():
    messages, query = repo(
        MessageRepository, rows=[message_row("user", "Hi", "2026-09-19T10:00:00")]
    )

    message = messages.add(CONVERSATION_ID, "user", "Hi")

    assert message.role == "user"
    assert query.calls == [
        (
            "insert",
            ({"conversation_id": CONVERSATION_ID, "role": "user", "content": "Hi"},),
            {},
        )
    ]


def test_message_list_recent_returns_oldest_first():
    # The query asks for newest first, so the fake returns rows in that order.
    messages, query = repo(
        MessageRepository,
        rows=[
            message_row("assistant", "Hello!", "2026-09-19T10:00:02"),
            message_row("user", "Hi", "2026-09-19T10:00:01"),
        ],
    )

    result = messages.list_recent(CONVERSATION_ID, limit=5)

    assert [m.content for m in result] == ["Hi", "Hello!"]
    assert ("order", ("created_at",), {"desc": True}) in query.calls
    assert ("limit", (5,), {}) in query.calls


def test_state_get_returns_none_when_no_row():
    state, _ = repo(ConversationStateRepository, rows=[])

    assert state.get(CONVERSATION_ID) is None


def test_state_save_upserts_slots_as_iso_dates():
    saved_row = {
        "conversation_id": CONVERSATION_ID,
        "check_in": "2026-10-21",
        "check_out": None,
        "guest_count": 2,
    }
    state, query = repo(ConversationStateRepository, rows=[saved_row])

    result = state.save(CONVERSATION_ID, date(2026, 10, 21), None, 2)

    assert result.check_in == date(2026, 10, 21)
    assert result.check_out is None
    (name, args, kwargs), = query.calls
    assert name == "upsert"
    assert kwargs == {"on_conflict": "conversation_id"}
    row = args[0]
    assert row["check_in"] == "2026-10-21"
    assert row["check_out"] is None
    assert row["guest_count"] == 2
    assert row["updated_at"]


def test_state_reset_clears_all_slots():
    state, query = repo(
        ConversationStateRepository,
        rows=[{"conversation_id": CONVERSATION_ID, "check_in": None, "check_out": None, "guest_count": None}],
    )

    state.reset(CONVERSATION_ID)

    row = query.calls[0][1][0]
    assert (row["check_in"], row["check_out"], row["guest_count"]) == (None, None, None)
