from datetime import date
from uuid import uuid4

import pytest

from app.models.availability import AvailabilityResult, AvailableRoom
from app.models.chat import (
    AvailabilityChatResponse,
    ErrorChatResponse,
    SlotCollectionChatResponse,
    TextChatResponse,
)
from app.models.slots import Slots
from app.services.chat_messages import (
    availability_message,
    format_date,
    history_text,
    invalid_slot_message,
    slot_collection_message,
)

OCT_21 = date(2026, 10, 21)
OCT_23 = date(2026, 10, 23)


def room(name, price, total):
    return AvailableRoom(
        room_type_id=uuid4(),
        name=name,
        max_guests=4,
        price_per_night=price,
        total_price=total,
        breakfast_included=True,
        rooms_available=3,
    )


def result(rooms=(), guests=2, nights=2, party_too_large=False):
    return AvailabilityResult(
        check_in=OCT_21,
        check_out=OCT_23,
        guest_count=guests,
        nights=nights,
        rooms=list(rooms),
        party_too_large=party_too_large,
    )


def test_dates_read_unambiguously():
    assert format_date(date(2026, 10, 1)) == "1 Oct 2026"
    assert format_date(date(2027, 1, 23)) == "23 Jan 2027"


# --- asking for missing details ------------------------------------------------------------------


@pytest.mark.parametrize(
    "slots,expected",
    [
        (
            Slots(),
            "I'd be happy to check availability. "
            "Please tell me your check-in date, check-out date and number of guests.",
        ),
        (
            Slots(check_in=OCT_21),
            "Thanks! So far I have check-in on 21 Oct 2026. "
            "Please tell me your check-out date and number of guests.",
        ),
        (
            Slots(check_in=OCT_21, guest_count=2),
            "Thanks! So far I have check-in on 21 Oct 2026 and 2 guests. "
            "Please tell me your check-out date.",
        ),
        (
            Slots(check_in=OCT_21, check_out=OCT_23),
            "Thanks! So far I have check-in on 21 Oct 2026 and check-out on 23 Oct 2026. "
            "Please tell me your number of guests.",
        ),
        (
            Slots(guest_count=1),
            "Thanks! So far I have 1 guest. Please tell me your check-in date and check-out date.",
        ),
        (
            Slots(check_out=OCT_23, guest_count=3),
            "Thanks! So far I have check-out on 23 Oct 2026 and 3 guests. "
            "Please tell me your check-in date.",
        ),
    ],
)
def test_slot_collection_message(slots, expected):
    assert slot_collection_message(slots) == expected


@pytest.mark.parametrize(
    "field,ending",
    [
        ("check_in", "Please tell me a new check-in date."),
        ("check_out", "Please tell me a new check-out date."),
        ("guest_count", "How many guests will be staying?"),
    ],
)
def test_invalid_slot_message_explains_then_asks_again(field, ending):
    text = invalid_slot_message("The check-in date can't be in the past.", field)

    assert text == f"The check-in date can't be in the past. {ending}"


# --- availability answers ------------------------------------------------------------------------


def test_message_for_available_rooms():
    text = availability_message(result([room("Family Suite", 8500, 17000)], guests=3))

    assert text == (
        "Good news! These rooms are available for 3 guests from 21 Oct 2026 to 23 Oct 2026 (2 nights):"
    )


def test_message_uses_singular_wording():
    text = availability_message(
        AvailabilityResult(
            check_in=OCT_21,
            check_out=date(2026, 10, 22),
            guest_count=1,
            nights=1,
            rooms=[room("Deluxe Room", 4500, 4500)],
        )
    )

    assert "1 guest " in text and "(1 night)" in text


def test_message_when_everything_is_booked():
    text = availability_message(result())

    assert text == (
        "I'm sorry, we have no rooms available for 2 guests from 21 Oct 2026 to 23 Oct 2026. "
        "Would you like to try different dates?"
    )


def test_message_when_no_room_is_big_enough():
    text = availability_message(result(guests=6, party_too_large=True))

    assert text == (
        "I'm sorry, none of our rooms can accommodate 6 guests in a single room. "
        "Please contact the hotel directly to arrange more than one room."
    )


# --- what is stored in the history ---------------------------------------------------------------


def availability_response(rooms):
    return AvailabilityChatResponse(
        message="Good news! These rooms are available:",
        check_in=OCT_21,
        check_out=OCT_23,
        guest_count=3,
        nights=2,
        rooms=rooms,
    )


def test_stored_availability_reply_lists_the_rooms_because_cards_are_not_stored():
    stored = history_text(
        availability_response([room("Family Suite", 8500, 17000), room("Executive Suite", 12000, 24000)]),
        "₹",
    )

    assert stored == (
        "Good news! These rooms are available:\n"
        "- Family Suite: ₹8,500 per night, ₹17,000 total\n"
        "- Executive Suite: ₹12,000 per night, ₹24,000 total"
    )


def test_stored_availability_reply_without_rooms_is_just_the_message():
    assert history_text(availability_response([]), "₹") == "Good news! These rooms are available:"


@pytest.mark.parametrize(
    "response",
    [
        TextChatResponse(message="Yes, we have a pool."),
        SlotCollectionChatResponse(message="Which dates?", missing_fields=["check_in"], slots=Slots()),
        ErrorChatResponse(message="oops", code="x"),
    ],
)
def test_other_replies_are_stored_as_their_message(response):
    assert history_text(response, "₹") == response.message
