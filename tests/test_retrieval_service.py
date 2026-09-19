from datetime import time
from uuid import uuid4

import pytest

from app.exceptions import HotelNotFound
from app.models.entities import Amenity, Hotel, Policy, RoomType
from app.services.retrieval_service import RetrievalService, select_categories

HOTEL_ID = "02e96bf4-29ff-484b-8c19-13cbf708402c"

HOTEL = Hotel(
    id=HOTEL_ID,
    slug="ocean-view-resort",
    name="Ocean View Resort",
    check_in_time=time(15, 0),
    check_out_time=time(11, 0),
)
AMENITY = Amenity(id=uuid4(), hotel_id=HOTEL_ID, name="Swimming Pool")
POLICY = Policy(id=uuid4(), hotel_id=HOTEL_ID, policy_type="pets", content="Pets are not allowed.")
ROOM = RoomType(
    id=uuid4(), hotel_id=HOTEL_ID, name="Deluxe Room", max_guests=2, price_per_night=4500, total_rooms=10
)

ALL = ["amenities", "policies", "rooms"]


# --- which categories a question needs -----------------------------------------------------------


@pytest.mark.parametrize(
    "question,categories",
    [
        # the guide's scenarios and the assignment's example questions
        ("What time is check-in?", []),
        ("What time is check-out?", []),
        ("Does the hotel have a swimming pool?", ["amenities"]),
        ("What amenities do you offer?", ["amenities"]),
        ("Do you have a lake?", ["amenities"]),  # guide: retrieve amenities, model says no lake
        ("Is breakfast included?", ["policies", "rooms"]),
        ("Which room is suitable for three guests?", ["rooms"]),
        ("What is the cancellation policy?", ["policies"]),
        # hotel record only
        ("Where is the hotel located?", []),
        ("What is your address?", []),
        # single categories
        ("Is there a gym?", ["amenities"]),
        ("Do you have wifi?", ["amenities"]),
        ("Is there a spa?", ["amenities"]),
        ("Do you offer airport pickup?", ["amenities"]),
        ("Are pets allowed?", ["policies"]),
        ("Can I bring my dog?", ["policies"]),
        ("Is parking available?", ["policies"]),
        ("Can I get a refund?", ["policies"]),
        ("How much is the family suite?", ["rooms"]),
        ("Which is your cheapest room?", ["rooms"]),
        # several categories at once
        ("Is there a spa and what is the cancellation policy?", ["amenities", "policies"]),
        ("What time does the restaurant open for breakfast?", ALL),
        ("Where can I park?", ["policies"]),
        # wording and case
        ("SWIMMING POOL???", ["amenities"]),
        ("is there a Pool", ["amenities"]),
    ],
)
def test_question_routing(question, categories):
    assert select_categories(question) == (categories, False)


@pytest.mark.parametrize(
    "question",
    [
        "Is there a casino?",  # an amenity we have no keyword for: load all so the model can compare
        "Tell me about the hotel",
        "Thanks!",
        "Is it free?",
        "",
    ],
)
def test_unmatched_questions_load_everything(question):
    assert select_categories(question) == (ALL, True)


@pytest.mark.parametrize(
    "question",
    ["Is there a spatial map?", "Do you serve barbecue?", "Any disparity in prices?"],
)
def test_keywords_match_whole_words_only(question):
    assert select_categories(question)[0] != ["amenities"]


# --- the service ---------------------------------------------------------------------------------


class FakeRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def get(self, hotel_id):
        self.calls += 1
        return self.rows

    def list_for_hotel(self, hotel_id):
        self.calls += 1
        return self.rows


def build(hotel=HOTEL):
    repos = dict(hotels=FakeRepo(hotel), amenities=FakeRepo([AMENITY]), policies=FakeRepo([POLICY]), rooms=FakeRepo([ROOM]))
    service = RetrievalService(HOTEL_ID, repos["hotels"], repos["amenities"], repos["policies"], repos["rooms"])
    return service, repos


def calls(repos):
    return {name: repo.calls for name, repo in repos.items()}


def test_only_the_needed_categories_are_queried():
    service, repos = build()

    context = service.retrieve("Are pets allowed?")

    assert calls(repos) == {"hotels": 1, "amenities": 0, "policies": 1, "rooms": 0}
    assert context.categories == ["policies"]
    assert context.policies == [POLICY]
    assert context.amenities == [] and context.room_types == []
    assert context.fallback is False


def test_hotel_only_questions_run_a_single_query():
    service, repos = build()

    context = service.retrieve("What time is check-in?")

    assert calls(repos) == {"hotels": 1, "amenities": 0, "policies": 0, "rooms": 0}
    assert context.hotel == HOTEL
    assert context.categories == []


def test_unmatched_question_falls_back_to_everything():
    service, repos = build()

    context = service.retrieve("Is there a casino?")

    assert calls(repos) == {"hotels": 1, "amenities": 1, "policies": 1, "rooms": 1}
    assert context.fallback is True
    assert (context.amenities, context.policies, context.room_types) == ([AMENITY], [POLICY], [ROOM])


def test_multi_category_question_loads_each_category_once():
    service, repos = build()

    context = service.retrieve("Is breakfast included?")

    assert calls(repos) == {"hotels": 1, "amenities": 0, "policies": 1, "rooms": 1}
    assert context.categories == ["policies", "rooms"]


def test_missing_hotel_is_a_setup_error_and_stops_early():
    service, repos = build(hotel=None)

    with pytest.raises(HotelNotFound):
        service.retrieve("What amenities do you offer?")

    assert calls(repos) == {"hotels": 1, "amenities": 0, "policies": 0, "rooms": 0}
