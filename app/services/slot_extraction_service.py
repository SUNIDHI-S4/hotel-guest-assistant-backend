import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import dateparser

from app.clock import hotel_today
from app.models.slots import Slots

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_SEPARATOR = r"\s*(?:-|–|—|to|till|until|through|thru)\s*(?:the\s+)?"
_YEAR = r"(?:,?\s*(\d{4}))?"

_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip
_NUMBER = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# --- date phrases, tried in this order; a phrase overlapping an earlier match is dropped ----------

_RANGE_DAYS_THEN_MONTH = re.compile(
    rf"\b{_DAY}{_SEPARATOR}{_DAY}\s+(?:of\s+)?({_MONTH})\b\.?{_YEAR}", re.I
)  # 21-23 October
_RANGE_MONTH_THEN_DAYS = re.compile(
    rf"\b({_MONTH})\b\.?\s+{_DAY}{_SEPARATOR}{_DAY}\b(?!\s*(?:of\s+)?{_MONTH}\b){_YEAR}", re.I
)  # October 21-23 (but not "Oct 21 to 23 Nov")
_ENDS_WITH_MONTH = re.compile(rf"\b{_MONTH}\b\.?\s*$", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_WITH_YEAR = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b")
_NUMERIC_NO_YEAR = re.compile(r"\b(\d{1,2})/(\d{1,2})\b(?!/)")
_DAY_THEN_MONTH = re.compile(rf"\b{_DAY}\s+(?:of\s+)?({_MONTH})\b\.?{_YEAR}", re.I)
_MONTH_THEN_DAY = re.compile(rf"\b({_MONTH})\b\.?\s+{_DAY}\b{_YEAR}", re.I)
_DAY_AFTER_TOMORROW = re.compile(r"\bday\s+after\s+tomorrow\b", re.I)
_TOMORROW = re.compile(r"\btomorrow\b", re.I)
_TODAY = re.compile(r"\b(?:today|tonight)\b", re.I)
_IN_N_DAYS = re.compile(rf"\bin\s+{_NUMBER}\s+days?\b", re.I)
_WEEKDAY = re.compile(rf"\b(?:(this|next|coming|upcoming)\s+)?({'|'.join(_WEEKDAYS)})\b", re.I)

# "the 23rd" on its own: only meaningful as a check-out day when the check-in is already known.
_BARE_ORDINAL_DAY = re.compile(r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b", re.I)

# --- which slot a date belongs to, judged from the words right before it -------------------------

_FILLER = r"(?:\s*(?:on|date|is|at|of|the|:))*\W*$"
_CHECK_IN_CUE = re.compile(
    rf"(?<![a-z])(?:check(?:ing)?[\s-]*in(?:\s+date)?|arriv(?:e|es|ing|al)|from|start(?:s|ing)?|begin(?:s|ning)?){_FILLER}"
)
_CHECK_OUT_CUE = re.compile(
    rf"(?<![a-z])(?:check(?:ing)?[\s-]*out(?:\s+date)?|leav(?:e|es|ing)|depart(?:s|ing|ure)?|until|till|to|through|thru|out){_FILLER}"
)

# --- stay length and party size ------------------------------------------------------------------

_NIGHTS = re.compile(
    r"\b(\d{1,2}|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*-?\s*nights?\b",
    re.I,
)
_TOTAL_GUESTS = re.compile(
    rf"\b{_NUMBER}\s+(?:guests?|people|ppl|persons?|pax|travell?ers?|of us)\b", re.I
)
_GROUP_OF = re.compile(rf"\b(?:family|party|group|team|couple)\s+of\s+{_NUMBER}\b", re.I)
_PEOPLE_BY_TYPE = re.compile(
    rf"\b{_NUMBER}\s+(?:adults?|children|child|kids?|infants?|babies|baby|toddlers?|teens?)\b", re.I
)
_WE_ARE = re.compile(rf"\b(?:we\s+are|we're|we\s+will\s+be|there\s+(?:are|will\s+be))\s+{_NUMBER}\b", re.I)
_FOR_N = re.compile(
    rf"\bfor\s+{_NUMBER}\b(?!\s*(?:nights?|days?|weeks?|st\b|nd\b|rd\b|th\b|[/.-]\d|{_MONTH}\b))", re.I
)
_JUST_ME = re.compile(r"\b(?:just\s+me|only\s+me|myself|solo|alone|single\s+travell?er)\b", re.I)
_COUPLE = re.compile(
    r"\b(?:(?:a\s+)?couple(?!\s+of)|me\s+and\s+my\s+(?:wife|husband|partner|spouse|girlfriend|boyfriend|friend)"
    r"|my\s+(?:wife|husband|partner|spouse)\s+and\s+(?:i|me))\b",
    re.I,
)
_BARE_NUMBER = re.compile(
    rf"\s*{_NUMBER}(?:\s*(?:guests?|people|persons?|adults?|pax))?\s*[.!]?\s*", re.I
)


@dataclass
class _Found:
    start: int
    end: int
    check_in: date | None = None  # set for ranges and for cue-labelled dates
    check_out: date | None = None
    single: date | None = None  # a date whose role is decided later
    is_weekday: bool = False  # "sunday" carries no date of its own, so it may need shifting later


def _to_int(token: str) -> int:
    return int(token) if token.isdigit() else _WORD_NUMBERS[token.lower()]


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


class SlotExtractionService:
    """Pulls check-in, check-out and guest count out of free text.

    Deterministic on purpose: regex finds the phrases, dateparser normalises month-name
    dates. No LLM is involved. Only slots found in the given message are returned; the
    caller merges them with what the conversation already knows.
    """

    def __init__(self, today: Callable[[], date] = hotel_today):
        self._today = today

    def extract(self, message: str, current: Slots | None = None) -> Slots:
        current = current or Slots()
        found = self._find_dates(message)
        check_in, check_out = self._assign_dates(found, current)
        check_out = self._shift_weekday_after_check_in(found, check_in or current.check_in, check_out)

        if not found:
            check_out = check_out or self._bare_day_as_check_out(message, current)

        masked = self._mask(message, found)

        if check_out is None:
            nights = self._nights(masked)
            start = check_in or current.check_in
            if nights and start:
                check_out = start + timedelta(days=nights)

        return Slots(
            check_in=check_in,
            check_out=check_out,
            guest_count=self._guest_count(masked, current),
        )

    # --- dates -------------------------------------------------------------------------------

    def _find_dates(self, text: str) -> list[_Found]:
        found: list[_Found] = []

        def add(match: re.Match, is_weekday: bool = False, **dates: date | None) -> None:
            if any(dates.values()) and not any(
                match.start() < f.end and f.start < match.end() for f in found
            ):
                found.append(_Found(match.start(), match.end(), is_weekday=is_weekday, **dates))

        for m in _RANGE_DAYS_THEN_MONTH.finditer(text):
            if _ENDS_WITH_MONTH.search(text[: m.start()]):
                continue  # "Oct 21 to 23 Nov": the 21 belongs to the October before it
            year = int(m.group(4)) if m.group(4) else None
            add(
                m,
                check_in=self._named_month_date(m.group(1), m.group(3), year),
                check_out=self._named_month_date(m.group(2), m.group(3), year),
            )
        for m in _RANGE_MONTH_THEN_DAYS.finditer(text):
            year = int(m.group(4)) if m.group(4) else None
            add(
                m,
                check_in=self._named_month_date(m.group(2), m.group(1), year),
                check_out=self._named_month_date(m.group(3), m.group(1), year),
            )
        for m in _ISO.finditer(text):
            add(m, single=_safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        for m in _NUMERIC_WITH_YEAR.finditer(text):
            year = int(m.group(3))
            year += 2000 if year < 100 else 0
            add(m, single=self._numeric_date(int(m.group(1)), int(m.group(2)), year))
        for m in _NUMERIC_NO_YEAR.finditer(text):
            add(m, single=self._numeric_date(int(m.group(1)), int(m.group(2)), None))
        for m in _DAY_THEN_MONTH.finditer(text):
            year = int(m.group(3)) if m.group(3) else None
            add(m, single=self._named_month_date(m.group(1), m.group(2), year))
        for m in _MONTH_THEN_DAY.finditer(text):
            year = int(m.group(3)) if m.group(3) else None
            add(m, single=self._named_month_date(m.group(2), m.group(1), year))

        today = self._today()
        for m in _DAY_AFTER_TOMORROW.finditer(text):
            add(m, single=today + timedelta(days=2))
        for m in _TOMORROW.finditer(text):
            add(m, single=today + timedelta(days=1))
        for m in _TODAY.finditer(text):
            add(m, single=today)
        for m in _IN_N_DAYS.finditer(text):
            add(m, single=today + timedelta(days=_to_int(m.group(1))))
        for m in _WEEKDAY.finditer(text):
            weekday = self._weekday_date(m.group(2).lower(), (m.group(1) or "").lower())
            add(m, is_weekday=True, single=weekday)

        found.sort(key=lambda f: f.start)
        self._label_by_cue(text, found)
        return found

    def _label_by_cue(self, text: str, found: list[_Found]) -> None:
        """Turn single dates into check-in/check-out when the words before them say which."""
        previous_end = 0
        for item in found:
            if item.single is not None:
                before = text[previous_end : item.start][-40:].lower()
                if _CHECK_OUT_CUE.search(before):
                    item.check_out, item.single = item.single, None
                elif _CHECK_IN_CUE.search(before):
                    item.check_in, item.single = item.single, None
            previous_end = item.end

    def _assign_dates(
        self, found: list[_Found], current: Slots
    ) -> tuple[date | None, date | None]:
        check_in = next((f.check_in for f in found if f.check_in), None)
        check_out = next((f.check_out for f in found if f.check_out), None)
        unlabelled = [f.single for f in found if f.single]

        free = [name for name, value in (("in", check_in), ("out", check_out)) if value is None]
        if len(unlabelled) == 1 and len(free) == 2:
            # A lone date with no cue: it answers whichever date the conversation still needs.
            free = ["out"] if current.check_in and not current.check_out else ["in"]

        for slot, value in zip(free, unlabelled):
            if slot == "in":
                check_in = value
            else:
                check_out = value
        return check_in, check_out

    @staticmethod
    def _shift_weekday_after_check_in(
        found: list[_Found], check_in: date | None, check_out: date | None
    ) -> date | None:
        """'Friday to Sunday': the Sunday must fall after the Friday, not before it."""
        if not (check_in and check_out and check_out <= check_in):
            return check_out
        if any(f.is_weekday and check_out in (f.check_out, f.single) for f in found):
            return check_out + timedelta(days=7 * ((check_in - check_out).days // 7 + 1))
        return check_out

    def _bare_day_as_check_out(self, text: str, current: Slots) -> date | None:
        """'the 23rd' after a check-in is known means that day of the check-in month (or the next)."""
        if not current.check_in or current.check_out:
            return None
        match = _BARE_ORDINAL_DAY.search(text)
        if not match:
            return None
        day = int(match.group(1))
        year, month = current.check_in.year, current.check_in.month
        candidate = _safe_date(year, month, day)
        if candidate is None or candidate <= current.check_in:
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
            candidate = _safe_date(year, month, day)
        return candidate

    def _named_month_date(self, day: str, month: str, year: int | None) -> date | None:
        today = self._today()
        parsed = self._parse_named(int(day), month, year or today.year)
        if parsed and year is None and parsed < today:
            parsed = self._parse_named(int(day), month, today.year + 1)
        return parsed

    @staticmethod
    def _parse_named(day: int, month: str, year: int) -> date | None:
        parsed = dateparser.parse(
            f"{day} {month} {year}", settings={"DATE_ORDER": "DMY"}, languages=["en"]
        )
        return parsed.date() if parsed else None

    def _numeric_date(self, first: int, second: int, year: int | None) -> date | None:
        # Day first (India). Fall back to month/day when the first number can't be a day-first date.
        day, month = (second, first) if second > 12 >= first else (first, second)
        today = self._today()
        candidate = _safe_date(year or today.year, month, day)
        if candidate and year is None and candidate < today:
            candidate = _safe_date(today.year + 1, month, day)
        return candidate

    def _weekday_date(self, weekday: str, qualifier: str) -> date:
        today = self._today()
        target = _WEEKDAYS.index(weekday)
        if qualifier == "next":
            # "next Friday" is the Friday of the following calendar week (Mon-Sun).
            return today + timedelta(days=7 - today.weekday() + target)
        return today + timedelta(days=(target - today.weekday()) % 7 or 7)

    @staticmethod
    def _mask(text: str, found: list[_Found]) -> str:
        """Blank out date phrases so their digits are never mistaken for guests or nights."""
        chars = list(text)
        for item in found:
            chars[item.start : item.end] = " " * (item.end - item.start)
        return "".join(chars)

    # --- nights and guests -------------------------------------------------------------------

    @staticmethod
    def _nights(text: str) -> int | None:
        match = _NIGHTS.search(text)
        return _to_int(match.group(1)) if match else None

    @staticmethod
    def _guest_count(text: str, current: Slots) -> int | None:
        # The last stated total wins: "2 guests... actually make it 3 guests" is a correction.
        totals = list(_TOTAL_GUESTS.finditer(text))
        if totals:
            return _to_int(totals[-1].group(1))
        if match := _GROUP_OF.search(text):
            return _to_int(match.group(1))

        by_type = [_to_int(m.group(1)) for m in _PEOPLE_BY_TYPE.finditer(text)]
        if by_type:
            return sum(by_type)

        for pattern in (_WE_ARE, _FOR_N):
            if match := pattern.search(text):
                return _to_int(match.group(1))

        if _JUST_ME.search(text):
            return 1
        if _COUPLE.search(text):
            return 2

        # A bare "3" only answers the guest question once the dates are settled.
        if current.guest_count is None and current.check_in and current.check_out:
            if match := _BARE_NUMBER.fullmatch(text):
                return _to_int(match.group(1))
        return None


@lru_cache
def get_slot_extraction_service() -> SlotExtractionService:
    return SlotExtractionService()
