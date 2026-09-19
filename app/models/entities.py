from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator


class Hotel(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    check_in_time: time
    check_out_time: time


class Amenity(BaseModel):
    id: UUID
    hotel_id: UUID
    name: str
    description: str | None = None


class Policy(BaseModel):
    id: UUID
    hotel_id: UUID
    policy_type: str
    content: str


class RoomType(BaseModel):
    id: UUID
    hotel_id: UUID
    name: str
    description: str | None = None
    max_guests: int
    price_per_night: float
    breakfast_included: bool = False
    total_rooms: int

    @field_validator("breakfast_included", mode="before")
    @classmethod
    def _null_means_no_breakfast(cls, value):
        return False if value is None else value


class Booking(BaseModel):
    id: UUID
    hotel_id: UUID
    room_type_id: UUID
    check_in_date: date
    check_out_date: date
    guest_count: int
    booking_status: str


class Message(BaseModel):
    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ConversationState(BaseModel):
    conversation_id: UUID
    check_in: date | None = None
    check_out: date | None = None
    guest_count: int | None = None
