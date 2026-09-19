from datetime import time
from uuid import uuid4

import pytest

from app.models.entities import Amenity, Hotel, Policy, RoomType
from app.models.retrieval import RetrievedContext
from app.services.context_builder import ContextBuilder

HOTEL_ID = "02e96bf4-29ff-484b-8c19-13cbf708402c"

builder = ContextBuilder("₹")


def make_hotel(**overrides):
    fields = dict(
        id=HOTEL_ID,
        slug="ocean-view-resort",
        name="Ocean View Resort",
        description="A luxury beachfront resort.",
        address="123 Beach Road",
        city="Goa",
        state="Goa",
        country="India",
        check_in_time=time(15, 0),
        check_out_time=time(11, 0),
    )
    return Hotel(**{**fields, **overrides})


def make_room(**overrides):
    fields = dict(
        id=uuid4(),
        hotel_id=HOTEL_ID,
        name="Deluxe Room",
        description="Comfortable room with garden view.",
        max_guests=2,
        price_per_night=4500,
        breakfast_included=True,
        total_rooms=10,
    )
    return RoomType(**{**fields, **overrides})


def make_context(hotel=None, categories=(), **rows):
    return RetrievedContext(hotel=hotel or make_hotel(), categories=list(categories), fallback=False, **rows)


def test_full_context_reads_as_expected():
    context = make_context(
        categories=["amenities", "policies", "rooms"],
        amenities=[
            Amenity(id=uuid4(), hotel_id=HOTEL_ID, name="Swimming Pool", description="Outdoor infinity swimming pool with ocean view"),
            Amenity(id=uuid4(), hotel_id=HOTEL_ID, name="Gym", description="Fully equipped fitness center"),
        ],
        policies=[
            Policy(id=uuid4(), hotel_id=HOTEL_ID, policy_type="cancellation", content="Free cancellation up to 24 hours before check-in."),
        ],
        room_types=[make_room(), make_room(name="Family Suite", description=None, max_guests=4, price_per_night=8500, breakfast_included=False)],
    )

    assert builder.build(context) == (
        "HOTEL\n"
        "Name: Ocean View Resort\n"
        "Description: A luxury beachfront resort.\n"
        "Location: 123 Beach Road, Goa, India\n"
        "Check-in time: 3:00 PM\n"
        "Check-out time: 11:00 AM\n"
        "\n"
        "AMENITIES\n"
        "- Swimming Pool: Outdoor infinity swimming pool with ocean view\n"
        "- Gym: Fully equipped fitness center\n"
        "\n"
        "POLICIES\n"
        "- Cancellation: Free cancellation up to 24 hours before check-in.\n"
        "\n"
        "ROOM TYPES\n"
        "- Deluxe Room: Comfortable room with garden view. Sleeps up to 2 guests. ₹4,500 per night. Breakfast included.\n"
        "- Family Suite: Sleeps up to 4 guests. ₹8,500 per night. Breakfast not included."
    )


def test_only_loaded_categories_appear():
    text = builder.build(make_context(categories=["policies"], policies=[]))

    assert "HOTEL" in text and "POLICIES" in text
    assert "AMENITIES" not in text and "ROOM TYPES" not in text


def test_hotel_only_context_has_just_the_hotel_section():
    text = builder.build(make_context())

    assert text.startswith("HOTEL\n")
    assert "\n\n" not in text


def test_an_empty_category_says_so_instead_of_disappearing():
    text = builder.build(make_context(categories=["amenities"], amenities=[]))

    assert "AMENITIES\n(none listed)" in text


def test_room_counts_are_never_included():
    text = builder.build(make_context(categories=["rooms"], room_types=[make_room(total_rooms=10)]))

    assert "10" not in text.replace("11:00", "").replace("10:", "")
    assert "total" not in text.lower()
    assert "available" not in text.lower()


@pytest.mark.parametrize(
    "amount,symbol,expected",
    [
        (4500, "₹", "₹4,500"),
        (12000.0, "₹", "₹12,000"),
        (4500.5, "₹", "₹4,500.50"),
        (999, "$", "$999"),
        (8500, "", "8,500"),
    ],
)
def test_price_formatting(amount, symbol, expected):
    text = ContextBuilder(symbol).build(
        make_context(categories=["rooms"], room_types=[make_room(price_per_night=amount)])
    )

    assert f"{expected} per night." in text


@pytest.mark.parametrize(
    "hour,minute,expected",
    [(0, 0, "12:00 AM"), (9, 5, "9:05 AM"), (11, 59, "11:59 AM"), (12, 0, "12:00 PM"), (12, 30, "12:30 PM"), (15, 0, "3:00 PM"), (23, 45, "11:45 PM")],
)
def test_times_use_a_twelve_hour_clock(hour, minute, expected):
    text = builder.build(make_context(hotel=make_hotel(check_in_time=time(hour, minute))))

    assert f"Check-in time: {expected}" in text


def test_location_skips_repeats_and_gaps():
    assert "Location: 123 Beach Road, Goa, India" in builder.build(make_context())
    assert "Location: Goa, India" in builder.build(make_context(hotel=make_hotel(address=None)))
    assert "Location" not in builder.build(
        make_context(hotel=make_hotel(address=None, city=None, state=None, country=None))
    )


def test_missing_descriptions_are_left_out():
    text = builder.build(
        make_context(
            hotel=make_hotel(description=None),
            categories=["amenities"],
            amenities=[Amenity(id=uuid4(), hotel_id=HOTEL_ID, name="Gym", description=None)],
        )
    )

    assert "Description:" not in text
    assert "- Gym\n" in text + "\n"


def test_policy_types_become_readable_labels():
    text = builder.build(
        make_context(
            categories=["policies"],
            policies=[Policy(id=uuid4(), hotel_id=HOTEL_ID, policy_type="late_checkout", content="Ask at reception.")],
        )
    )

    assert "- Late Checkout: Ask at reception." in text
