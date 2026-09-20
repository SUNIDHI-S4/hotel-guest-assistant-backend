from datetime import date

import pytest

from app.models.slots import Slots
from app.services.intent_service import IntentService
from app.services.slot_extraction_service import SlotExtractionService

TODAY = date(2026, 9, 19)
OCT_21 = date(2026, 10, 21)
OCT_23 = date(2026, 10, 23)

extractor = SlotExtractionService(today=lambda: TODAY)
intents = IntentService()

NOTHING = Slots()
DATES_KNOWN = Slots(check_in=OCT_21, check_out=OCT_23)
CHECK_IN_ONLY = Slots(check_in=OCT_21)
SEARCH_DONE = Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2)


def intent_of(message, current=NOTHING):
    """Run the same two steps the chat service does: extract slots, then detect the intent."""
    return intents.detect(message, extractor.extract(message, current), current)


# --- starting a room search ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Do you have rooms available?",  # the guide's example
        "Is there availability?",
        "Do you have vacancies?",
        "Can I book a room?",
        "I want to make a reservation",
        "Any free rooms?",
        "I'd like to book a room for 2 people",
        "Are you fully booked?",
        "Do you have a room on 21 October?",
        "Oct 21 to Oct 23",
        "21-23 October, 2 guests",
        "tomorrow for 2 nights",
        "I'll arrive tomorrow",
        "from 21 Oct to 23 Oct do you have a family suite",
    ],
)
def test_room_search_messages(message):
    assert intent_of(message) == "availability"


# --- answering the assistant's own questions -----------------------------------------------------


@pytest.mark.parametrize(
    "message,current",
    [
        ("23rd October", CHECK_IN_ONLY),  # the check-out question
        ("the 23rd", CHECK_IN_ONLY),
        ("Oct 21 to 23", Slots(guest_count=2)),  # the dates question
        ("3", DATES_KNOWN),  # the guests question
        ("3 guests", DATES_KNOWN),
        ("we are 4", DATES_KNOWN),
        ("Nov 3", SEARCH_DONE),  # a fresh date after results were shown
        ("What about Nov 3 to Nov 5?", SEARCH_DONE),
        ("What about 4 guests?", SEARCH_DONE),  # changing the party size
        ("for 4 people", SEARCH_DONE),
    ],
)
def test_replies_that_continue_a_search(message, current):
    assert intent_of(message, current) == "availability"


# --- hotel questions -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "What time is check-in?",
        "Do you have a swimming pool?",
        "What amenities do you offer?",
        "Is breakfast included?",
        "Which room is suitable for three guests?",
        "What is the cancellation policy?",
        "How much is the family suite?",
        "Do you have rooms with an ocean view?",
        "Hello",
        "Thanks!",
        "3",  # a number means nothing without a search under way
        # availability words that are about something else
        "Can I cancel my booking?",
        "Is the spa available?",
        "Is parking available?",
        "Is the airport shuttle available at 6am?",
        "Book a table at the restaurant",
        # a day named only as a point in time
        "Is the pool open today?",
        "What time is breakfast tomorrow?",
        "What time is check-in on Sunday?",
    ],
)
def test_hotel_questions(message):
    assert intent_of(message) == "knowledge"


@pytest.mark.parametrize(
    "message",
    [
        "Does the family suite fit 4 people?",
        "Which room is suitable for three guests?",
        "Is the pool ok for 4 people?",
        "How much is the Deluxe Room?",
        "What is the cancellation policy?",
        "Is breakfast included?",
        "Is the pool open today?",
    ],
)
@pytest.mark.parametrize("current", [CHECK_IN_ONLY, DATES_KNOWN, SEARCH_DONE], ids=["check-in", "dates", "done"])
def test_hotel_questions_stay_hotel_questions_while_a_search_is_under_way(message, current):
    assert intent_of(message, current) == "knowledge"


def test_a_repeated_availability_question_restarts_the_flow():
    assert intent_of("Do you have rooms available?", SEARCH_DONE) == "availability"
