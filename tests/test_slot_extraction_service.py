from datetime import date

import pytest

from app.models.slots import Slots
from app.services.slot_extraction_service import SlotExtractionService

TODAY = date(2026, 9, 19)  # a Saturday

extractor = SlotExtractionService(today=lambda: TODAY)


def slots(check_in=None, check_out=None, guests=None):
    return Slots(check_in=check_in, check_out=check_out, guest_count=guests)


OCT_21 = date(2026, 10, 21)
OCT_23 = date(2026, 10, 23)


def check(message, expected, current=None):
    assert extractor.extract(message, current) == expected, message


# --- explicit dates ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected",
    [
        ("I'd like a room from 21 October to 23 October for 2 guests", slots(OCT_21, OCT_23, 2)),
        ("Oct 21 to Oct 23, 3 people", slots(OCT_21, OCT_23, 3)),
        ("21st to 23rd October", slots(OCT_21, OCT_23)),
        ("21-23 October, 2 adults and 1 child", slots(OCT_21, OCT_23, 3)),
        ("October 21-23", slots(OCT_21, OCT_23)),
        ("Oct 21 - 23", slots(OCT_21, OCT_23)),
        ("21 to 23 Oct 2027", slots(date(2027, 10, 21), date(2027, 10, 23))),
        ("Oct 21 to 23 Nov", slots(OCT_21, date(2026, 11, 23))),
        ("Check in on 21 Oct and check out on 23 Oct", slots(OCT_21, OCT_23)),
        ("arriving Oct 21, leaving Oct 23", slots(OCT_21, OCT_23)),
        ("check out 23 Oct, check in 21 Oct", slots(OCT_21, OCT_23)),
        ("21/10/2026 to 23/10/2026", slots(OCT_21, OCT_23)),
        ("21-10-2026 to 23-10-2026", slots(OCT_21, OCT_23)),
        ("2026-10-21 to 2026-10-23", slots(OCT_21, OCT_23)),
        ("21/10 to 23/10", slots(OCT_21, OCT_23)),
        ("21st of October till 23rd of October", slots(OCT_21, OCT_23)),
        ("Sept 25 to Sept 27", slots(date(2026, 9, 25), date(2026, 9, 27))),
        ("from the 21st to the 24th of October", slots(OCT_21, date(2026, 10, 24))),
        ("10th-12th Nov", slots(date(2026, 11, 10), date(2026, 11, 12))),
        ("OCTOBER 21 TO OCTOBER 23 FOR 2 GUESTS", slots(OCT_21, OCT_23, 2)),
    ],
)
def test_explicit_dates(message, expected):
    check(message, expected)


def test_single_date_without_context_is_the_check_in():
    check("Do you have a room on 21 October?", slots(OCT_21))


@pytest.mark.parametrize(
    "message,expected",
    [
        ("19 September", slots(TODAY)),  # today is a valid check-in
        ("20 September", slots(date(2026, 9, 20))),
        ("18 September", slots(date(2027, 9, 18))),  # already passed -> next year
        ("Sep 5", slots(date(2027, 9, 5))),
        ("21 October 2027", slots(date(2027, 10, 21))),
        ("5/6", slots(date(2027, 6, 5))),  # day first: 5 June, next occurrence
        ("10/21", slots(OCT_21)),  # 21 can't be a month, so read it as month/day
        ("31 February", slots()),
        ("31/02/2026", slots()),
    ],
)
def test_year_rules_and_invalid_dates(message, expected):
    check(message, expected)


# --- relative dates ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected",
    [
        ("today", slots(TODAY)),
        ("tonight for 2 nights", slots(TODAY, date(2026, 9, 21))),
        ("tomorrow", slots(date(2026, 9, 20))),
        ("from tomorrow to day after tomorrow", slots(date(2026, 9, 20), date(2026, 9, 21))),
        ("in 3 days for 2 nights", slots(date(2026, 9, 22), date(2026, 9, 24))),
        ("next friday for 3 nights", slots(date(2026, 9, 25), date(2026, 9, 28))),
        ("this friday to sunday", slots(date(2026, 9, 25), date(2026, 9, 27))),
        ("friday to sunday", slots(date(2026, 9, 25), date(2026, 9, 27))),
        ("sunday to friday", slots(date(2026, 9, 20), date(2026, 9, 25))),
        ("I need a room tomorrow for 2 people", slots(date(2026, 9, 20), None, 2)),
    ],
)
def test_relative_dates(message, expected):
    check(message, expected)


def test_next_weekday_means_the_following_calendar_week():
    # On Wednesday 16 Sep: "this friday" is the 18th, "next friday" is the 25th.
    midweek = SlotExtractionService(today=lambda: date(2026, 9, 16))

    assert midweek.extract("this friday").check_in == date(2026, 9, 18)
    assert midweek.extract("next friday").check_in == date(2026, 9, 25)


# --- stay length ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected",
    [
        ("21 October for 2 nights", slots(OCT_21, OCT_23)),
        ("21 October, a night", slots(OCT_21, date(2026, 10, 22))),
        ("21 October for two nights with three guests", slots(OCT_21, OCT_23, 3)),
        ("a 3-night stay from 21 October", slots(OCT_21, date(2026, 10, 24))),
        ("21 to 23 October for 5 nights", slots(OCT_21, OCT_23)),  # explicit dates win
    ],
)
def test_nights_set_the_check_out(message, expected):
    check(message, expected)


def test_nights_alone_do_not_invent_dates():
    check("we'd stay for 2 nights", slots())


def test_nights_count_from_a_known_check_in():
    check("for 2 nights", slots(None, OCT_23), current=slots(OCT_21))


# --- guest counts --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,guests",
    [
        ("3 guests", 3),
        ("three guests please", 3),
        ("for 4 people", 4),
        ("for 4", 4),
        ("we are 4", 4),
        ("we're 5 in total", 5),
        ("there are 4 of us", 4),
        ("family of 5", 5),
        ("a party of 6", 6),
        ("2 adults", 2),
        ("2 adults and 2 kids", 4),
        ("2 adults, 1 child and 1 infant", 4),
        ("just me", 1),
        ("solo trip", 1),
        ("a couple", 2),
        ("me and my wife", 2),
        ("Which room is suitable for three guests?", 3),
        ("0 guests", 0),  # passed through so the availability service can reject it
    ],
)
def test_guest_counts(message, guests):
    check(message, slots(guests=guests))


def test_total_guest_count_beats_a_breakdown():
    check("4 guests including 2 adults", slots(guests=4))


@pytest.mark.parametrize(
    "message,guests",
    [
        ("2 ppl", 2),
        ("2 guests. Actually make it 3 guests", 3),
        ("for 2 people, no wait, 4 people", 4),
    ],
)
def test_shorthand_and_corrections(message, guests):
    check(message, slots(guests=guests))


@pytest.mark.parametrize(
    "message",
    [
        "3 rooms",
        "for 2 nights",
        "for 21 October",
        "21 October to 23 October",
        "Oct 21-23",
        "check-in at 3",
    ],
)
def test_digits_that_are_not_guests_are_ignored(message):
    assert extractor.extract(message).guest_count is None


# --- follow-up replies using the conversation so far --------------------------------------------


@pytest.mark.parametrize(
    "message,expected",
    [
        ("23rd October", slots(None, OCT_23)),
        ("23 Oct", slots(None, OCT_23)),
        ("Oct 25", slots(None, date(2026, 10, 25))),
        ("the 23rd", slots(None, OCT_23)),
        ("23rd", slots(None, OCT_23)),
        ("the 15th", slots(None, date(2026, 11, 15))),  # 15th is before check-in -> next month
        ("check out on 23 Oct", slots(None, OCT_23)),
        ("sunday", slots(None, date(2026, 10, 25))),  # the Sunday after check-in
    ],
)
def test_answers_to_the_check_out_question(message, expected):
    check(message, expected, current=slots(OCT_21))


def test_bare_day_rolls_over_the_year_end():
    check("the 3rd", slots(None, date(2027, 1, 3)), current=slots(date(2026, 12, 28)))


def test_lone_date_answers_the_check_in_question():
    check("21 October", slots(OCT_21), current=slots())
    check("21 October", slots(OCT_21), current=slots(None, None, 3))


def test_cue_words_override_the_context():
    check("check in on 21 Oct", slots(OCT_21), current=slots(None, None, 2))
    check("I'd leave on 23 Oct", slots(None, OCT_23), current=slots())


def test_new_date_when_both_dates_are_known_starts_a_new_search():
    check("3 Nov", slots(date(2026, 11, 3)), current=slots(OCT_21, OCT_23, 2))


@pytest.mark.parametrize("message", ["3", "three", "3 guests", "3 people.", " 3 "])
def test_answers_to_the_guest_question(message):
    check(message, slots(guests=3), current=slots(OCT_21, OCT_23))


def test_bare_number_is_not_a_guest_count_until_dates_are_known():
    check("3", slots(), current=slots())
    check("3", slots(), current=slots(OCT_21))


def test_bare_number_is_ignored_when_guests_are_already_known():
    check("3", slots(), current=slots(OCT_21, OCT_23, 2))


# --- messages with nothing to extract ------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "",
        "   ",
        "What time is check-in?",
        "Is breakfast included?",
        "Do you have rooms available?",
        "Do you have a swimming pool?",
        "What is the cancellation policy?",
        "I may want to book a march or may stay",
    ],
)
def test_nothing_to_extract(message):
    check(message, slots())


def test_missing_fields_in_guide_order():
    assert Slots().missing_fields == ["check_in", "check_out", "guest_count"]
    assert Slots(check_in=OCT_21, guest_count=2).missing_fields == ["check_out"]
    assert Slots(check_in=OCT_21, check_out=OCT_23, guest_count=2).missing_fields == []
