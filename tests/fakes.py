from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from app.models.entities import ConversationState, Message
from app.models.slots import Slots


class FakeQuery:
    """Stands in for a Supabase query builder: records every chained call.

    `errors` are raised by successive execute() calls (one per call) before rows are returned.
    """

    def __init__(self, rows=None, errors=None):
        self.rows = rows if rows is not None else []
        self.errors = list(errors or [])
        self.calls: list[tuple] = []
        self.executions = 0

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return record

    def execute(self):
        self.executions += 1
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(data=self.rows)


class FakeClient:
    def __init__(self, query: FakeQuery):
        self.query = query
        self.tables: list[str] = []

    def table(self, name: str) -> FakeQuery:
        self.tables.append(name)
        return self.query


# --- in-memory stand-ins for the conversation repositories -------------------------------------


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
