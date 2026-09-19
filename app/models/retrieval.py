from typing import Literal

from pydantic import BaseModel

from app.models.entities import Amenity, Hotel, Policy, RoomType

Category = Literal["amenities", "policies", "rooms"]


class RetrievedContext(BaseModel):
    """The hotel data pulled from the database to answer one question."""

    hotel: Hotel  # always loaded: name, description, address, check-in/out times
    categories: list[Category]  # which optional categories were loaded
    fallback: bool  # True when the question matched nothing, so everything was loaded
    amenities: list[Amenity] = []
    policies: list[Policy] = []
    room_types: list[RoomType] = []
