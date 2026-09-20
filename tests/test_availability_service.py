from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.exceptions import InvalidAvailabilityRequest
from app.models.entities import Booking, RoomType
from app.services.availability_service import AvailabilityService

HOTEL_ID = "02e96bf4-29ff-484b-8c19-13cbf708402c"
TODAY = date(2026, 9, 19)


def make_room(name, max_guests, price, total, breakfast=True):
    return RoomType(
        id=uuid4(),
        hotel_id=HOTEL_ID,
        name=name,
        description=f"{name} description",
        max_guests=max_guests,
        price_per_night=price,
        breakfast_included=breakfast,
        total_rooms=total,
    )


DELUXE = make_room("Deluxe Room", 2, 4500, 10)
FAMILY = make_room("Family Suite", 4, 8500, 5)
EXECUTIVE = make_room("Executive Suite", 5, 12000, 3)


def make_booking(room, check_in, check_out, status="confirmed"):
    return Booking(
        id=uuid4(),
        hotel_id=HOTEL_ID,
        room_type_id=room.id,
        check_in_date=check_in,
        check_out_date=check_out,
        guest_count=2,
        booking_status=status,
    )


class FakeRoomTypes:
    def __init__(self, rooms):
        self.rooms = rooms
        self.capacity_requests: list[int] = []

    def list_for_capacity(self, hotel_id, guest_count):
        self.capacity_requests.append(guest_count)
        fitting = [r for r in self.rooms if r.max_guests >= guest_count]
        return sorted(fitting, key=lambda r: (r.max_guests, r.price_per_night))


class FakeBookings:
    """Applies the same overlap rule as the real repository."""

    def __init__(self, bookings):
        self.bookings = bookings
        self.requests: list[tuple[date, date]] = []

    def list_overlapping(self, hotel_id, check_in, check_out):
        self.requests.append((check_in, check_out))
        return [
            b
            for b in self.bookings
            if b.booking_status != "cancelled"
            and b.check_in_date < check_out
            and b.check_out_date > check_in
        ]


# The seed data from sql/seed.sql
SEED_BOOKINGS = [
    make_booking(DELUXE, date(2026, 10, 18), date(2026, 10, 21)),
    make_booking(FAMILY, date(2026, 10, 20), date(2026, 10, 22)),
    make_booking(FAMILY, date(2026, 10, 21), date(2026, 10, 24)),
    make_booking(EXECUTIVE, date(2026, 10, 25), date(2026, 10, 28)),
]


def build(bookings=SEED_BOOKINGS, rooms=(DELUXE, FAMILY, EXECUTIVE)):
    room_repo, booking_repo = FakeRoomTypes(list(rooms)), FakeBookings(list(bookings))
    service = AvailabilityService(HOTEL_ID, room_repo, booking_repo, today=lambda: TODAY)
    return service, room_repo, booking_repo


def names(result):
    return [room.name for room in result.rooms]


def remaining(result):
    return {room.name: room.rooms_available for room in result.rooms}


# --- results ---------------------------------------------------------------------------------


def test_returns_all_fitting_rooms_smallest_first():
    service, _, _ = build(bookings=[])

    result = service.check(date(2026, 12, 1), date(2026, 12, 3), 2)

    assert names(result) == ["Deluxe Room", "Family Suite", "Executive Suite"]


def test_excludes_rooms_too_small_for_the_party():
    service, _, _ = build(bookings=[])

    result = service.check(date(2026, 12, 1), date(2026, 12, 3), 3)

    assert names(result) == ["Family Suite", "Executive Suite"]


def test_subtracts_overlapping_bookings_from_inventory():
    service, _, _ = build()

    result = service.check(date(2026, 10, 21), date(2026, 10, 23), 3)

    assert remaining(result) == {"Family Suite": 3, "Executive Suite": 3}


def test_rooms_booked_out_are_left_out():
    bookings = [make_booking(EXECUTIVE, date(2026, 11, 1), date(2026, 11, 5)) for _ in range(3)]
    service, _, _ = build(bookings=bookings)

    result = service.check(date(2026, 11, 2), date(2026, 11, 4), 5)

    assert result.rooms == []


def test_larger_room_still_offered_when_smaller_is_sold_out():
    bookings = [make_booking(DELUXE, date(2026, 11, 1), date(2026, 11, 5)) for _ in range(10)]
    service, _, _ = build(bookings=bookings)

    result = service.check(date(2026, 11, 2), date(2026, 11, 4), 2)

    assert names(result) == ["Family Suite", "Executive Suite"]


def test_same_day_turnover_is_not_a_clash():
    service, _, _ = build()

    # The Deluxe booking checks out on 21 Oct, exactly when this stay begins.
    result = service.check(date(2026, 10, 21), date(2026, 10, 22), 2)

    assert remaining(result)["Deluxe Room"] == 10


def test_stay_ending_on_a_check_in_day_is_not_a_clash():
    service, _, _ = build()

    # Executive Suite is booked from 25 Oct; a stay ending on the 25th leaves it free.
    result = service.check(date(2026, 10, 23), date(2026, 10, 25), 5)

    assert remaining(result) == {"Executive Suite": 3}


def test_cancelled_bookings_do_not_reduce_availability():
    cancelled = [make_booking(FAMILY, date(2026, 11, 1), date(2026, 11, 5), "cancelled")]
    service, _, _ = build(bookings=cancelled)

    result = service.check(date(2026, 11, 2), date(2026, 11, 4), 4)

    assert remaining(result)["Family Suite"] == 5


def test_overbooked_data_never_shows_negative_availability():
    bookings = [make_booking(EXECUTIVE, date(2026, 11, 1), date(2026, 11, 5)) for _ in range(4)]
    service, _, _ = build(bookings=bookings)

    result = service.check(date(2026, 11, 2), date(2026, 11, 4), 5)

    assert result.rooms == []


def test_prices_and_stay_length():
    service, _, _ = build(bookings=[])

    result = service.check(date(2026, 12, 1), date(2026, 12, 4), 2)

    assert result.nights == 3
    deluxe = result.rooms[0]
    assert deluxe.price_per_night == 4500
    assert deluxe.total_price == 13500
    assert deluxe.breakfast_included is True
    assert (result.check_in, result.check_out, result.guest_count) == (
        date(2026, 12, 1),
        date(2026, 12, 4),
        2,
    )


def test_party_too_large_for_any_room_skips_booking_lookup():
    service, _, booking_repo = build()

    result = service.check(date(2026, 12, 1), date(2026, 12, 3), 6)

    assert result.rooms == []
    assert booking_repo.requests == []


def test_searches_the_requested_dates_and_party_size():
    service, room_repo, booking_repo = build()

    service.check(date(2026, 12, 1), date(2026, 12, 3), 4)

    assert room_repo.capacity_requests == [4]
    assert booking_repo.requests == [(date(2026, 12, 1), date(2026, 12, 3))]


# --- validation ------------------------------------------------------------------------------


def test_check_in_today_is_allowed():
    service, _, _ = build(bookings=[])

    result = service.check(TODAY, TODAY + timedelta(days=1), 2)

    assert result.nights == 1


@pytest.mark.parametrize(
    "check_in,check_out,guests,message_part",
    [
        (TODAY - timedelta(days=1), TODAY + timedelta(days=2), 2, "in the past"),
        (TODAY + timedelta(days=5), TODAY + timedelta(days=5), 2, "after the check-in"),
        (TODAY + timedelta(days=5), TODAY + timedelta(days=4), 2, "after the check-in"),
        (TODAY + timedelta(days=5), TODAY + timedelta(days=7), 0, "at least 1"),
        (TODAY + timedelta(days=5), TODAY + timedelta(days=7), -2, "at least 1"),
    ],
)
def test_invalid_requests_are_rejected_before_touching_the_database(
    check_in, check_out, guests, message_part
):
    service, room_repo, booking_repo = build()

    with pytest.raises(InvalidAvailabilityRequest) as error:
        service.check(check_in, check_out, guests)

    assert message_part in error.value.message
    assert room_repo.capacity_requests == []
    assert booking_repo.requests == []


# --- what the chat flow needs from the result and the errors -------------------------------------


@pytest.mark.parametrize(
    "check_in,check_out,guests,field",
    [
        (TODAY + timedelta(days=5), TODAY + timedelta(days=7), 0, "guest_count"),
        (TODAY - timedelta(days=1), TODAY + timedelta(days=2), 2, "check_in"),
        (TODAY + timedelta(days=5), TODAY + timedelta(days=5), 2, "check_out"),
        (TODAY + timedelta(days=5), TODAY + timedelta(days=4), 2, "check_out"),
    ],
)
def test_validation_errors_name_the_slot_to_ask_for_again(check_in, check_out, guests, field):
    service, _, _ = build()

    with pytest.raises(InvalidAvailabilityRequest) as error:
        service.check(check_in, check_out, guests)

    assert error.value.field == field


def test_no_room_big_enough_is_flagged_apart_from_sold_out():
    service, _, _ = build()

    too_large = service.check(date(2026, 12, 1), date(2026, 12, 3), 6)
    fits = service.check(date(2026, 12, 1), date(2026, 12, 3), 2)

    assert too_large.rooms == [] and too_large.party_too_large is True
    assert fits.party_too_large is False


def test_sold_out_is_not_reported_as_too_large():
    bookings = [make_booking(EXECUTIVE, date(2026, 11, 1), date(2026, 11, 5)) for _ in range(3)]
    service, _, _ = build(bookings=bookings)

    result = service.check(date(2026, 11, 2), date(2026, 11, 4), 5)

    assert result.rooms == [] and result.party_too_large is False
