from datetime import date, datetime
from uuid import uuid4

import pytest

from app.exceptions import ConversationNotFound
from app.models.entities import ConversationState, Message
from app.models.slots import Slots
from app.services.conversation_service import ConversationService

HOTEL_ID = "02e96bf4-29ff-484b-8c19-13cbf708402c"
CONVERSATION_ID = uuid4()

OCT_21 = date(2026, 10, 21)
OCT_23 = date(2026, 10, 23)
NOV_3 = date(2026, 11, 3)


class FakeConversations:
    def __init__(self, exists=True):
        self.known = exists
        self.created_for: list[str] = []

    def create(self, hotel_id):
        self.created_for.append(hotel_id)
        return "new-conversation-id"

    def exists(self, conversation_id):
        return self.known


class FakeMessages:
    def __init__(self):
        self.added: list[tuple] = []
        self.rows: list[Message] = []
        self.limits: list[int] = []

    def add(self, conversation_id, role, content):
        self.added.append((conversation_id, role, content))
        return Message(
            id=uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=datetime(2026, 9, 19, 10, 0, 0),
        )

    def list_recent(self, conversation_id, limit):
        self.limits.append(limit)
        return self.rows


class FakeStates:
    def __init__(self, state: Slots | None = None):
        self.state = state
        self.saved: list[tuple] = []
        self.resets = 0
        self.reads = 0

    def get(self, conversation_id):
        self.reads += 1
        if self.state is None:
            return None
        return ConversationState(
            conversation_id=conversation_id,
            check_in=self.state.check_in,
            check_out=self.state.check_out,
            guest_count=self.state.guest_count,
        )

    def save(self, conversation_id, check_in, check_out, guest_count):
        self.saved.append((check_in, check_out, guest_count))
        self.state = Slots(check_in=check_in, check_out=check_out, guest_count=guest_count)

    def reset(self, conversation_id):
        self.resets += 1
        self.state = Slots()


def build(exists=True, state=None):
    conversations, messages, states = FakeConversations(exists), FakeMessages(), FakeStates(state)
    return ConversationService(HOTEL_ID, conversations, messages, states), conversations, messages, states


# --- conversations and messages ------------------------------------------------------------------


def test_create_uses_the_default_hotel():
    service, conversations, _, _ = build()

    assert service.create() == "new-conversation-id"
    assert conversations.created_for == [HOTEL_ID]


def test_require_exists_raises_for_unknown_conversation():
    service, _, _, _ = build(exists=False)

    with pytest.raises(ConversationNotFound):
        service.require_exists(CONVERSATION_ID)


def test_add_message_stores_role_and_content():
    service, _, messages, _ = build()

    stored = service.add_message(CONVERSATION_ID, "user", "Do you have rooms?")

    assert messages.added == [(CONVERSATION_ID, "user", "Do you have rooms?")]
    assert stored.content == "Do you have rooms?"


def test_get_messages_returns_history_for_an_existing_conversation():
    service, _, messages, _ = build()
    messages.rows = [Message(
        id=uuid4(), conversation_id=CONVERSATION_ID, role="user", content="Hi",
        created_at=datetime(2026, 9, 19, 10, 0, 0),
    )]  # fmt: skip

    result = service.get_messages(CONVERSATION_ID, limit=5)

    assert [m.content for m in result] == ["Hi"]
    assert messages.limits == [5]


def test_get_messages_of_unknown_conversation_raises_instead_of_returning_empty():
    service, _, messages, _ = build(exists=False)

    with pytest.raises(ConversationNotFound):
        service.get_messages(CONVERSATION_ID)
    assert messages.limits == []


# --- slots ---------------------------------------------------------------------------------------


def test_get_slots_is_empty_before_anything_is_saved():
    service, _, _, _ = build(state=None)

    assert service.get_slots(CONVERSATION_ID) == Slots()


def test_get_slots_returns_the_saved_state():
    saved = Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2)
    service, _, _, _ = build(state=saved)

    assert service.get_slots(CONVERSATION_ID) == saved


def test_new_slots_are_saved_when_nothing_was_known():
    service, _, _, states = build(state=None)

    merged = service.update_slots(CONVERSATION_ID, Slots(check_in=OCT_21, guest_count=2))

    assert merged == Slots(check_in=OCT_21, guest_count=2)
    assert states.saved == [(OCT_21, None, 2)]


def test_slots_accumulate_across_messages():
    service, _, _, _ = build(state=None)

    service.update_slots(CONVERSATION_ID, Slots(check_in=OCT_21))
    service.update_slots(CONVERSATION_ID, Slots(guest_count=3))
    merged = service.update_slots(CONVERSATION_ID, Slots(check_out=OCT_23))

    assert merged == Slots(check_in=OCT_21, check_out=OCT_23, guest_count=3)
    assert service.get_slots(CONVERSATION_ID) == merged


def test_new_values_replace_old_ones_and_others_are_kept():
    service, _, _, _ = build(state=Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2))

    merged = service.update_slots(CONVERSATION_ID, Slots(guest_count=4))

    assert merged == Slots(check_in=OCT_21, check_out=OCT_23, guest_count=4)


def test_a_guest_count_of_zero_is_kept_so_validation_can_reject_it():
    service, _, _, _ = build(state=Slots(guest_count=2))

    merged = service.update_slots(CONVERSATION_ID, Slots(guest_count=0))

    assert merged.guest_count == 0


def test_nothing_is_written_when_the_message_changes_nothing():
    service, _, _, states = build(state=Slots(check_in=OCT_21, guest_count=2))

    service.update_slots(CONVERSATION_ID, Slots())
    service.update_slots(CONVERSATION_ID, Slots(guest_count=2))

    assert states.saved == []


def test_nothing_is_written_for_a_message_with_no_slots_and_no_state():
    service, _, _, states = build(state=None)

    assert service.update_slots(CONVERSATION_ID, Slots()) == Slots()
    assert states.saved == []


def test_a_later_check_in_clears_the_old_check_out():
    service, _, _, states = build(state=Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2))

    merged = service.update_slots(CONVERSATION_ID, Slots(check_in=NOV_3))

    assert merged == Slots(check_in=NOV_3, check_out=None, guest_count=2)
    assert states.saved == [(NOV_3, None, 2)]


def test_a_check_in_before_the_saved_check_out_keeps_it():
    service, _, _, _ = build(state=Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2))

    merged = service.update_slots(CONVERSATION_ID, Slots(check_in=date(2026, 10, 22)))

    assert merged.check_out == OCT_23


def test_a_new_check_in_and_check_out_together_are_both_taken():
    service, _, _, _ = build(state=Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2))

    merged = service.update_slots(
        CONVERSATION_ID, Slots(check_in=NOV_3, check_out=date(2026, 11, 5))
    )

    assert merged == Slots(check_in=NOV_3, check_out=date(2026, 11, 5), guest_count=2)


def test_a_check_out_before_the_check_in_is_kept_for_validation_to_report():
    service, _, _, _ = build(state=Slots(check_in=OCT_23))

    merged = service.update_slots(CONVERSATION_ID, Slots(check_out=OCT_21))

    assert merged == Slots(check_in=OCT_23, check_out=OCT_21)


def test_passing_current_slots_avoids_a_second_read():
    current = Slots(check_in=OCT_21)
    service, _, _, states = build(state=current)

    service.update_slots(CONVERSATION_ID, Slots(guest_count=2), current=current)

    assert states.reads == 0
    assert states.saved == [(OCT_21, None, 2)]


def test_reset_clears_the_saved_slots():
    service, _, _, states = build(state=Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2))

    assert service.reset_slots(CONVERSATION_ID) == Slots()
    assert states.resets == 1
    assert service.get_slots(CONVERSATION_ID) == Slots()
