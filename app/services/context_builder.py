from datetime import time
from functools import lru_cache

from app.config import get_settings
from app.models.entities import Amenity, Hotel, RoomType
from app.models.retrieval import RetrievedContext


def _format_time(value: time) -> str:
    return f"{value.hour % 12 or 12}:{value.minute:02d} {'AM' if value.hour < 12 else 'PM'}"


def format_price(amount: float, currency_symbol: str) -> str:
    text = f"{amount:,.0f}" if amount == int(amount) else f"{amount:,.2f}"
    return f"{currency_symbol}{text}"


def _location(hotel: Hotel) -> str:
    parts: list[str] = []
    for part in (hotel.address, hotel.city, hotel.state, hotel.country):
        if part and (not parts or parts[-1] != part):  # "Goa, Goa" reads as a typo
            parts.append(part)
    return ", ".join(parts)


class ContextBuilder:
    """Turns retrieved rows into the plain-text facts block that goes into the prompt.

    Availability is deliberately absent (no room counts): it comes from the deterministic
    availability engine, never from the model's reading of the inventory.
    """

    def __init__(self, currency_symbol: str):
        self._currency = currency_symbol

    def build(self, context: RetrievedContext) -> str:
        sections = [self._hotel_section(context.hotel)]

        if "amenities" in context.categories:
            lines = [self._amenity_line(a) for a in context.amenities]
            sections.append(self._section("AMENITIES", lines))
        if "policies" in context.categories:
            lines = [f"- {p.policy_type.replace('_', ' ').title()}: {p.content}" for p in context.policies]
            sections.append(self._section("POLICIES", lines))
        if "rooms" in context.categories:
            sections.append(self._section("ROOM TYPES", [self._room_line(r) for r in context.room_types]))

        return "\n\n".join(sections)

    def _hotel_section(self, hotel: Hotel) -> str:
        lines = [f"Name: {hotel.name}"]
        if hotel.description:
            lines.append(f"Description: {hotel.description}")
        if location := _location(hotel):
            lines.append(f"Location: {location}")
        lines.append(f"Check-in time: {_format_time(hotel.check_in_time)}")
        lines.append(f"Check-out time: {_format_time(hotel.check_out_time)}")
        return "HOTEL\n" + "\n".join(lines)

    @staticmethod
    def _amenity_line(amenity: Amenity) -> str:
        details = []
        if amenity.description:
            details.append(amenity.description)
        if amenity.timings:
            details.append(f"Timings: {amenity.timings}")
        return f"- {amenity.name}: {'. '.join(details)}" if details else f"- {amenity.name}"

    @staticmethod
    def _section(title: str, lines: list[str]) -> str:
        # An empty section says so, so "nothing listed" is not mistaken for "not looked up".
        return title + "\n" + ("\n".join(lines) if lines else "(none listed)")

    def _room_line(self, room: RoomType) -> str:
        parts = [f"{room.name}:"]
        if room.description:
            parts.append(room.description)
        parts.append(f"Sleeps up to {room.max_guests} guests.")
        parts.append(f"{self._price(room.price_per_night)} per night.")
        parts.append("Breakfast included." if room.breakfast_included else "Breakfast not included.")
        return "- " + " ".join(parts)

    def _price(self, amount: float) -> str:
        return format_price(amount, self._currency)


@lru_cache
def get_context_builder() -> ContextBuilder:
    return ContextBuilder(get_settings().currency_symbol)
