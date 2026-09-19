import logging
import re
from functools import lru_cache

from app.config import get_settings
from app.exceptions import HotelNotFound
from app.models.retrieval import Category, RetrievedContext
from app.repositories.amenity_repository import AmenityRepository, get_amenity_repository
from app.repositories.hotel_repository import HotelRepository, get_hotel_repository
from app.repositories.policy_repository import PolicyRepository, get_policy_repository
from app.repositories.room_type_repository import RoomTypeRepository, get_room_type_repository

logger = logging.getLogger(__name__)


def _keywords(pattern: str) -> re.Pattern:
    return re.compile(rf"\b(?:{pattern})\b", re.I)


# Keyword rules that decide which hotel data a question needs. Categories overlap on purpose
# ("breakfast" is both a policy and a per-room fact), and a question may match several.
_AMENITIES = _keywords(
    r"amenit\w*|facilit\w*|pools?|swim\w*|gym|fitness|workout|spa|massage|wellness|restaurants?"
    r"|dining|dinner|lunch|food|bar|wi-?fi|internet|shuttle|airport|pick-?up|drop-?off|transfers?"
    r"|lake|beach|garden|view|services?|offer\w*|activit\w*"
)
_POLICIES = _keywords(
    r"polic\w*|cancel\w*|refund\w*|pets?|dogs?|cats?|animals?|parking|park|smok\w*|rules?|allow\w*"
    r"|permit\w*|deposit|prepay\w*|payments?|pay|no-?show|breakfast|terms|conditions"
)
_ROOMS = _keywords(
    r"rooms?|suites?|deluxe|executive|family|beds?|bedrooms?|sleep\w*|accommodat\w*|prices?|pricing"
    r"|costs?|rates?|charges?|cheap\w*|expensive|afford\w*|how\s+much|per\s+night|guests?|people"
    r"|persons?|adults?|kids?|children|child|capacity|breakfast|view|twin|double|king|queen"
)
# Questions the always-loaded hotel record answers by itself.
_PROPERTY = _keywords(
    r"check-?\s?in|check-?\s?out|checkin|checkout|arriv\w*|depart\w*|time|when|address|locat\w*"
    r"|where|city|country|directions?|contact|phone|email|hours"
)

_DATA_RULES: dict[Category, re.Pattern] = {
    "amenities": _AMENITIES,
    "policies": _POLICIES,
    "rooms": _ROOMS,
}
_ALL_CATEGORIES: list[Category] = ["amenities", "policies", "rooms"]


def select_categories(question: str) -> tuple[list[Category], bool]:
    """Which categories to load for a question, and whether we fell back to loading all.

    Unsure is never treated as "nothing to say": a question that matches no rule loads
    everything, so the model can see what the hotel does and doesn't have.
    """
    matched = [category for category, rule in _DATA_RULES.items() if rule.search(question)]
    if matched:
        return matched, False
    if _PROPERTY.search(question):
        return [], False  # the hotel record alone (times, address) covers it
    return list(_ALL_CATEGORIES), True


class RetrievalService:
    """Loads the hotel data relevant to a question with plain SQL lookups (no vector store)."""

    def __init__(
        self,
        hotel_id: str,
        hotels: HotelRepository,
        amenities: AmenityRepository,
        policies: PolicyRepository,
        room_types: RoomTypeRepository,
    ):
        self._hotel_id = hotel_id
        self._hotels = hotels
        self._amenities = amenities
        self._policies = policies
        self._room_types = room_types

    def retrieve(self, question: str) -> RetrievedContext:
        hotel = self._hotels.get(self._hotel_id)
        if hotel is None:
            logger.error("Hotel %s was not found in the database", self._hotel_id)
            raise HotelNotFound()

        categories, fallback = select_categories(question)
        logger.info("Retrieval categories=%s fallback=%s", categories or ["hotel only"], fallback)

        return RetrievedContext(
            hotel=hotel,
            categories=categories,
            fallback=fallback,
            amenities=self._amenities.list_for_hotel(self._hotel_id) if "amenities" in categories else [],
            policies=self._policies.list_for_hotel(self._hotel_id) if "policies" in categories else [],
            room_types=self._room_types.list_for_hotel(self._hotel_id) if "rooms" in categories else [],
        )


@lru_cache
def get_retrieval_service() -> RetrievalService:
    return RetrievalService(
        get_settings().default_hotel_id,
        get_hotel_repository(),
        get_amenity_repository(),
        get_policy_repository(),
        get_room_type_repository(),
    )
