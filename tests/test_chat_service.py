from datetime import date, time
from uuid import uuid4

import pytest

from app.exceptions import (
    AssistantRateLimited,
    AssistantUnavailable,
    ConversationNotFound,
    DatabaseError,
    InvalidAvailabilityRequest,
)
from app.models.availability import AvailabilityResult, AvailableRoom
from app.models.chat import (
    AvailabilityChatResponse,
    SlotCollectionChatResponse,
    TextChatResponse,
)
from app.models.entities import Amenity, Hotel
from app.models.retrieval import RetrievedContext
from app.models.slots import Slots
from app.services.chat_service import ChatService
from app.services.context_builder import ContextBuilder
from app.services.conversation_service import ConversationService
from app.services.intent_service import IntentService
from app.services.prompt_builder import PromptBuilder
from app.services.slot_extraction_service import SlotExtractionService
from tests.fakes import FakeConversations, FakeMessages, FakeStates

HOTEL_ID = "02e96bf4-29ff-484b-8c19-13cbf708402c"
CONVERSATION_ID = uuid4()
TODAY = date(2026, 9, 19)
OCT_21 = date(2026, 10, 21)
OCT_23 = date(2026, 10, 23)

HOTEL = Hotel(
    id=HOTEL_ID,
    slug="ocean-view-resort",
    name="Ocean View Resort",
    check_in_time=time(15, 0),
    check_out_time=time(11, 0),
)
CONTEXT = RetrievedContext(
    hotel=HOTEL,
    categories=["amenities"],
    fallback=False,
    amenities=[Amenity(id=uuid4(), hotel_id=HOTEL_ID, name="Swimming Pool", description="Outdoor infinity pool")],
)


def make_room(name, price, total, guests=4):
    return AvailableRoom(
        room_type_id=uuid4(),
        name=name,
        max_guests=guests,
        price_per_night=price,
        total_price=total,
        breakfast_included=True,
        rooms_available=3,
    )


FAMILY = make_room("Family Suite", 8500, 17000)
EXECUTIVE = make_room("Executive Suite", 12000, 24000, guests=5)


class RecordingMessages(FakeMessages):
    """Like the fake, but list_recent reflects what was added, as the real table would."""

    def add(self, conversation_id, role, content):
        message = super().add(conversation_id, role, content)
        self.rows.append(message)
        return message

    def list_recent(self, conversation_id, limit):
        return self.rows[-limit:]


class FakeAvailability:
    def __init__(self, rooms=(FAMILY, EXECUTIVE), party_too_large=False, error=None):
        self.rooms = list(rooms)
        self.party_too_large = party_too_large
        self.error = error
        self.calls: list[tuple] = []

    def check(self, check_in, check_out, guest_count):
        self.calls.append((check_in, check_out, guest_count))
        if self.error:
            raise self.error
        return AvailabilityResult(
            check_in=check_in,
            check_out=check_out,
            guest_count=guest_count,
            nights=(check_out - check_in).days,
            rooms=self.rooms,
            party_too_large=self.party_too_large,
        )


class FakeRetrieval:
    def __init__(self, error=None):
        self.error = error
        self.questions: list[str] = []

    def retrieve(self, question):
        self.questions.append(question)
        if self.error:
            raise self.error
        return CONTEXT


class FakeGemini:
    def __init__(self, answer="Yes, we have an outdoor infinity pool.", error=None):
        self.answer = answer
        self.error = error
        self.prompts: list = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.answer


class Rig:
    """A ChatService wired to fakes, with handles to inspect what happened."""

    def __init__(self, state=None, exists=True, availability=None, retrieval=None, gemini=None):
        self.messages = RecordingMessages()
        self.states = FakeStates(state)
        self.availability = availability or FakeAvailability()
        self.retrieval = retrieval or FakeRetrieval()
        self.gemini = gemini or FakeGemini()
        conversations = ConversationService(HOTEL_ID, FakeConversations(exists), self.messages, self.states)
        self.service = ChatService(
            conversations,
            SlotExtractionService(today=lambda: TODAY),
            IntentService(),
            self.availability,
            self.retrieval,
            PromptBuilder(ContextBuilder("₹")),
            self.gemini,
            "₹",
        )

    def send(self, message):
        return self.service.handle(CONVERSATION_ID, message)

    @property
    def saved(self):
        return [(m.role, m.content) for m in self.messages.rows]


# --- hotel questions -----------------------------------------------------------------------------


def test_hotel_question_is_answered_by_gemini_from_retrieved_facts():
    rig = Rig()

    response = rig.send("Do you have a swimming pool?")

    assert response == TextChatResponse(message="Yes, we have an outdoor infinity pool.")
    assert rig.retrieval.questions == ["Do you have a swimming pool?"]
    (prompt,) = rig.gemini.prompts
    assert "Swimming Pool: Outdoor infinity pool" in prompt.system_instruction
    assert [(t.role, t.text) for t in prompt.turns] == [("user", "Do you have a swimming pool?")]
    assert rig.availability.calls == []


def test_hotel_question_turn_is_saved_as_user_then_assistant():
    rig = Rig()

    rig.send("Do you have a swimming pool?")

    assert rig.saved == [
        ("user", "Do you have a swimming pool?"),
        ("assistant", "Yes, we have an outdoor infinity pool."),
    ]


def test_hotel_questions_do_not_touch_the_search_slots():
    rig = Rig()

    rig.send("Which room is suitable for three guests?")

    assert rig.states.saved == []


def test_follow_up_questions_carry_the_earlier_conversation_to_gemini():
    rig = Rig()
    rig.send("Tell me about the family suite")
    rig.gemini.answer = "Yes, breakfast is included."

    rig.send("Does it include breakfast?")

    second_prompt = rig.gemini.prompts[1]
    assert [(t.role, t.text) for t in second_prompt.turns] == [
        ("user", "Tell me about the family suite"),
        ("model", "Yes, we have an outdoor infinity pool."),
        ("user", "Does it include breakfast?"),
    ]


def test_current_question_is_not_duplicated_in_the_history_sent_to_gemini():
    rig = Rig()

    rig.send("Do you have a gym?")

    texts = [t.text for t in rig.gemini.prompts[0].turns]
    assert texts.count("Do you have a gym?") == 1


# --- availability: collecting details ------------------------------------------------------------


def test_asking_for_availability_asks_for_all_three_details():
    rig = Rig()

    response = rig.send("Do you have rooms available?")

    assert isinstance(response, SlotCollectionChatResponse)
    assert response.missing_fields == ["check_in", "check_out", "guest_count"]
    assert response.slots == Slots()
    assert "check-in date, check-out date and number of guests" in response.message
    assert rig.gemini.prompts == [] and rig.retrieval.questions == []  # no model call needed
    assert rig.availability.calls == []


def test_details_are_collected_over_several_messages_then_availability_runs():
    rig = Rig()

    first = rig.send("Do you have rooms available?")
    second = rig.send("Oct 21 to Oct 23")
    third = rig.send("2")

    assert first.missing_fields == ["check_in", "check_out", "guest_count"]
    assert isinstance(second, SlotCollectionChatResponse)
    assert second.missing_fields == ["guest_count"]
    assert second.slots == Slots(check_in=OCT_21, check_out=OCT_23)
    assert "check-in on 21 Oct 2026 and check-out on 23 Oct 2026" in second.message
    assert isinstance(third, AvailabilityChatResponse)
    assert rig.availability.calls == [(OCT_21, OCT_23, 2)]
    assert rig.states.state == Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2)


def test_everything_in_one_message_goes_straight_to_the_results():
    rig = Rig()

    response = rig.send("Do you have a room from 21 October to 23 October for 3 guests?")

    assert isinstance(response, AvailabilityChatResponse)
    assert rig.availability.calls == [(OCT_21, OCT_23, 3)]


def test_a_hotel_question_in_the_middle_of_a_search_does_not_lose_the_details():
    rig = Rig(state=Slots(check_in=OCT_21))

    answer = rig.send("What is the cancellation policy?")
    reply = rig.send("the 23rd")

    assert isinstance(answer, TextChatResponse)
    assert isinstance(reply, SlotCollectionChatResponse)
    assert reply.slots == Slots(check_in=OCT_21, check_out=OCT_23)
    assert reply.missing_fields == ["guest_count"]


# --- availability: results -----------------------------------------------------------------------


def test_results_carry_rooms_dates_and_a_readable_message():
    rig = Rig()

    response = rig.send("Room for 21 October to 23 October, 3 guests")

    assert isinstance(response, AvailabilityChatResponse)
    assert (response.check_in, response.check_out) == (OCT_21, OCT_23)
    assert (response.guest_count, response.nights) == (3, 2)
    assert [room.name for room in response.rooms] == ["Family Suite", "Executive Suite"]
    assert response.message == (
        "Good news! These rooms are available for 3 guests from 21 Oct 2026 to 23 Oct 2026 (2 nights):"
    )


def test_saved_availability_reply_lists_the_rooms_for_when_the_chat_is_reloaded():
    rig = Rig()

    rig.send("Room for 21 October to 23 October, 3 guests")

    role, content = rig.saved[1]
    assert role == "assistant"
    assert "- Family Suite: ₹8,500 per night, ₹17,000 total" in content
    assert "- Executive Suite: ₹12,000 per night, ₹24,000 total" in content


def test_nothing_free_gets_an_apology_and_no_rooms():
    rig = Rig(availability=FakeAvailability(rooms=[]))

    response = rig.send("Room for 21 October to 23 October, 2 guests")

    assert isinstance(response, AvailabilityChatResponse)
    assert response.rooms == []
    assert response.message.startswith("I'm sorry, we have no rooms available for 2 guests")


def test_a_party_too_big_for_any_room_says_so():
    rig = Rig(availability=FakeAvailability(rooms=[], party_too_large=True))

    response = rig.send("Room for 21 October to 23 October, 8 guests")

    assert "none of our rooms can accommodate 8 guests" in response.message


def test_results_do_not_call_gemini_or_retrieval():
    rig = Rig()

    rig.send("Room for 21 October to 23 October, 2 guests")

    assert rig.gemini.prompts == [] and rig.retrieval.questions == []


def test_details_are_kept_after_results_so_a_follow_up_can_change_one():
    rig = Rig(state=Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2))

    response = rig.send("What about 4 guests?")

    assert isinstance(response, AvailabilityChatResponse)
    assert rig.availability.calls == [(OCT_21, OCT_23, 4)]
    assert rig.states.state.guest_count == 4


def test_new_dates_after_results_replace_the_old_search():
    rig = Rig(state=Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2))

    response = rig.send("What about 3 Nov to 5 Nov?")

    assert isinstance(response, AvailabilityChatResponse)
    assert rig.availability.calls == [(date(2026, 11, 3), date(2026, 11, 5), 2)]


# --- availability: details that can't be searched ------------------------------------------------


def test_an_invalid_detail_is_explained_cleared_and_asked_again():
    error = InvalidAvailabilityRequest("The check-in date can't be in the past.", "check_in")
    rig = Rig(availability=FakeAvailability(error=error))

    response = rig.send("Room from 1 Sept 2026 to 3 Sept 2026 for 2 guests")

    assert isinstance(response, SlotCollectionChatResponse)
    assert response.missing_fields == ["check_in"]
    assert response.message == "The check-in date can't be in the past. Please tell me a new check-in date."
    assert response.slots.check_in is None
    assert response.slots.check_out == date(2026, 9, 3)
    assert rig.states.state.check_in is None  # what we saved matches what we asked for


def test_the_corrected_detail_then_completes_the_search():
    error = InvalidAvailabilityRequest("The check-in date can't be in the past.", "check_in")
    rig = Rig(availability=FakeAvailability(error=error))
    rig.send("Room from 1 Sept 2026 to 3 Sept 2026 for 2 guests")
    rig.availability.error = None

    corrected = rig.send("21 October")
    finished = rig.send("23rd October")

    # The new check-in is after the old September check-out, so that check-out is dropped too.
    assert isinstance(corrected, SlotCollectionChatResponse)
    assert corrected.missing_fields == ["check_out"]
    assert corrected.slots == Slots(check_in=OCT_21, guest_count=2)
    assert isinstance(finished, AvailabilityChatResponse)
    assert rig.availability.calls[-1] == (OCT_21, OCT_23, 2)


def test_an_invalid_request_with_no_named_field_is_not_swallowed():
    rig = Rig(availability=FakeAvailability(error=InvalidAvailabilityRequest("Odd request.")))

    with pytest.raises(InvalidAvailabilityRequest):
        rig.send("Room for 21 October to 23 October, 2 guests")


# --- failures leave nothing behind ---------------------------------------------------------------


def test_unknown_conversation_is_rejected_before_any_work():
    rig = Rig(exists=False)

    with pytest.raises(ConversationNotFound):
        rig.send("Do you have a swimming pool?")

    assert rig.gemini.prompts == [] and rig.retrieval.questions == [] and rig.saved == []


@pytest.mark.parametrize("error", [AssistantUnavailable(), AssistantRateLimited()])
def test_gemini_failure_is_raised_and_the_turn_is_not_saved(error):
    rig = Rig(gemini=FakeGemini(error=error))

    with pytest.raises(type(error)):
        rig.send("Do you have a swimming pool?")

    assert rig.saved == []


def test_retrying_after_a_gemini_failure_does_not_duplicate_the_question():
    rig = Rig(gemini=FakeGemini(error=AssistantUnavailable()))
    with pytest.raises(AssistantUnavailable):
        rig.send("Do you have a swimming pool?")
    rig.gemini.error = None

    rig.send("Do you have a swimming pool?")

    assert rig.saved.count(("user", "Do you have a swimming pool?")) == 1
    assert [(t.role, t.text) for t in rig.gemini.prompts[-1].turns] == [
        ("user", "Do you have a swimming pool?")
    ]


def test_database_failure_while_retrieving_is_raised_and_the_turn_is_not_saved():
    rig = Rig(retrieval=FakeRetrieval(error=DatabaseError()))

    with pytest.raises(DatabaseError):
        rig.send("What amenities do you offer?")

    assert rig.saved == [] and rig.gemini.prompts == []


def test_database_failure_during_availability_is_raised_and_the_turn_is_not_saved():
    rig = Rig(availability=FakeAvailability(error=DatabaseError()))

    with pytest.raises(DatabaseError):
        rig.send("Room for 21 October to 23 October, 2 guests")

    assert rig.saved == []


def test_each_successful_turn_saves_exactly_one_pair_of_messages():
    rig = Rig()

    rig.send("Do you have a swimming pool?")
    rig.send("Do you have rooms available?")
    rig.send("Oct 21 to Oct 23")

    assert [role for role, _ in rig.saved] == ["user", "assistant"] * 3
