from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.models.availability import AvailableRoom
from app.models.slots import Slots

MAX_MESSAGE_LENGTH = 1000

SlotName = Literal["check_in", "check_out", "guest_count"]


class ChatRequest(BaseModel):
    conversation_id: UUID
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    ]


class TextChatResponse(BaseModel):
    """An answer to a hotel question (amenities, policies, rooms, check-in times...)."""

    response_type: Literal["text"] = "text"
    message: str


class SlotCollectionChatResponse(BaseModel):
    """The guest wants availability but some details are still missing."""

    response_type: Literal["slot_collection"] = "slot_collection"
    message: str
    missing_fields: list[SlotName]
    # What has been understood so far, so the UI can show it back or prefill a form.
    slots: Slots


class AvailabilityChatResponse(BaseModel):
    """Search results; `rooms` is empty when nothing fits or everything is booked."""

    response_type: Literal["availability"] = "availability"
    message: str
    check_in: date
    check_out: date
    guest_count: int
    nights: int
    rooms: list[AvailableRoom]


class ErrorChatResponse(BaseModel):
    """Something went wrong while answering; `message` is safe to show to the guest."""

    response_type: Literal["error"] = "error"
    message: str
    code: str


ChatResponse = Annotated[
    TextChatResponse | SlotCollectionChatResponse | AvailabilityChatResponse | ErrorChatResponse,
    Field(discriminator="response_type"),
]
