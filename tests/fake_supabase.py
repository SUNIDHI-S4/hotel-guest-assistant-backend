"""An in-memory stand-in for the Supabase client, seeded with the hotel from sql/seed.sql.

Unlike tests/fakes.py (which only records the calls a repository makes), this one really
applies the filters, ordering and limits, so a whole request can run through the real
repositories and services and be judged on what comes back, not on which methods were called.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

HOTEL_ID = "00000000-0000-0000-0000-000000000000"  # matches DEFAULT_HOTEL_ID set in conftest.py

DELUXE_ID = "88da7bec-e9fe-48e3-bcb0-dc461b69b48f"
FAMILY_ID = "0d788df0-0fce-4a83-9816-1c739be18826"
EXECUTIVE_ID = "8708a59b-637e-4e5f-8f58-81840056f64a"


def seed_tables() -> dict[str, list[dict]]:
    """The rows of sql/seed.sql, shaped the way Supabase returns them (ISO strings for dates)."""
    stamp = "2026-09-01T09:00:00"
    room = lambda id, name, desc, guests, price: {  # noqa: E731
        "id": id, "hotel_id": HOTEL_ID, "name": name, "description": desc, "max_guests": guests,
        "price_per_night": price, "breakfast_included": True, "total_rooms": {DELUXE_ID: 10, FAMILY_ID: 5, EXECUTIVE_ID: 3}[id],
        "created_at": stamp,
    }  # fmt: skip
    booking = lambda room_id, start, end, guests: {  # noqa: E731
        "id": str(uuid4()), "hotel_id": HOTEL_ID, "room_type_id": room_id, "check_in_date": start,
        "check_out_date": end, "guest_count": guests, "booking_status": "confirmed", "created_at": stamp,
    }  # fmt: skip
    amenity = lambda name, desc, timings=None: {"id": str(uuid4()), "hotel_id": HOTEL_ID, "name": name, "description": desc, "timings": timings, "created_at": stamp}  # noqa: E731
    policy = lambda kind, text: {"id": str(uuid4()), "hotel_id": HOTEL_ID, "policy_type": kind, "content": text, "created_at": stamp}  # noqa: E731

    return {
        "hotels": [{
            "id": HOTEL_ID, "slug": "ocean-view-resort", "name": "Ocean View Resort",
            "description": "A luxury beachfront resort with premium amenities and family-friendly accommodations.",
            "address": "123 Beach Road", "city": "Goa", "state": "Goa", "country": "India",
            "check_in_time": "15:00:00", "check_out_time": "11:00:00", "created_at": stamp, "updated_at": stamp,
        }],  # fmt: skip
        "amenities": [
            amenity("Swimming Pool", "Outdoor infinity swimming pool with ocean view", "6:00 AM - 8:00 PM"),
            amenity("Gym", "Fully equipped fitness center", "24 hours"),
            amenity("Spa", "Wellness and spa treatments available", "9:00 AM - 8:00 PM"),
            amenity("Restaurant", "Multi-cuisine restaurant serving breakfast, lunch and dinner", "7:00 AM - 11:00 PM"),
            amenity("Free WiFi", "High-speed wireless internet throughout the property"),  # no fixed timing
            amenity("Airport Shuttle", "Paid airport pickup and drop service", "On request"),
        ],
        "policies": [
            policy("cancellation", "Free cancellation up to 24 hours before check-in."),
            policy("pets", "Pets are not allowed at the property."),
            policy("parking", "Complimentary on-site parking is available for guests."),
            policy("breakfast", "Complimentary breakfast is included for selected room types."),
        ],
        "room_types": [
            room(DELUXE_ID, "Deluxe Room", "Comfortable room with garden view.", 2, 4500.0),
            room(FAMILY_ID, "Family Suite", "Spacious suite suitable for families.", 4, 8500.0),
            room(EXECUTIVE_ID, "Executive Suite", "Premium suite with ocean view and lounge access.", 5, 12000.0),
        ],
        "bookings": [
            booking(DELUXE_ID, "2026-10-18", "2026-10-21", 2),
            booking(FAMILY_ID, "2026-10-20", "2026-10-22", 3),
            booking(FAMILY_ID, "2026-10-21", "2026-10-24", 4),
            booking(EXECUTIVE_ID, "2026-10-25", "2026-10-28", 4),
        ],
        "conversations": [],
        "messages": [],
        "conversation_state": [],
    }  # fmt: skip


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables = tables if tables is not None else seed_tables()
        self.queries: list[tuple[str, str]] = []  # (table, operation), in order, for assertions
        self._clock = datetime(2026, 9, 19, 10, 0, 0)
        self._failures: list[Exception] = []
        self._always: Exception | None = None

    # --- failure injection ---------------------------------------------------------------------

    def fail_next(self, error: Exception, times: int = 1) -> None:
        """The next `times` queries raise `error`, then things recover (a transient blip)."""
        self._failures += [error] * times

    def go_down(self, error: Exception) -> None:
        """Every query raises `error` until the test ends (an outage)."""
        self._always = error

    # --- the client interface ------------------------------------------------------------------

    def table(self, name: str) -> "FakeQuery":
        return FakeQuery(self, name)

    def now(self) -> str:
        self._clock += timedelta(milliseconds=1)  # strictly increasing, so ordering is stable
        return self._clock.isoformat()

    def check_failure(self) -> None:
        if self._always:
            raise self._always
        if self._failures:
            raise self._failures.pop(0)

    def count(self, table: str) -> int:
        return len(self.tables[table])


class FakeQuery:
    """The chainable query builder the repositories use (select/eq/order/limit/insert/upsert...)."""

    def __init__(self, db: FakeSupabase, table: str):
        self._db = db
        self._table = table
        self._operation = "select"
        self._columns = "*"
        self._filters: list = []
        self._orders: list[tuple[str, bool]] = []
        self._limit: int | None = None
        self._payload: dict | None = None
        self._conflict_key: str | None = None

    def select(self, columns: str = "*", **_):
        self._operation, self._columns = "select", columns
        return self

    def insert(self, payload: dict):
        self._operation, self._payload = "insert", payload
        return self

    def upsert(self, payload: dict, on_conflict: str | None = None):
        self._operation, self._payload, self._conflict_key = "upsert", payload, on_conflict
        return self

    def eq(self, column, value):
        self._filters.append(lambda row: row.get(column) == value)
        return self

    def neq(self, column, value):
        self._filters.append(lambda row: row.get(column) != value)
        return self

    def gt(self, column, value):
        self._filters.append(lambda row: row.get(column) > value)
        return self

    def gte(self, column, value):
        self._filters.append(lambda row: row.get(column) >= value)
        return self

    def lt(self, column, value):
        self._filters.append(lambda row: row.get(column) < value)
        return self

    def order(self, column, desc: bool = False):
        self._orders.append((column, desc))
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    def execute(self):
        self._db.queries.append((self._table, self._operation))
        self._db.check_failure()
        rows = self._db.tables[self._table]

        if self._operation == "insert":
            return self._respond([self._store(dict(self._payload))])

        if self._operation == "upsert":
            key = self._conflict_key
            existing = next((r for r in rows if key and r.get(key) == self._payload.get(key)), None)
            if existing is not None:
                existing.update(self._payload)
                return self._respond([existing])
            return self._respond([self._store(dict(self._payload))])

        matched = [row for row in rows if all(check(row) for check in self._filters)]
        for column, desc in reversed(self._orders):  # stable sorts, last key first
            matched.sort(key=lambda row: row[column], reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        return self._respond(matched)

    # --- helpers -------------------------------------------------------------------------------

    def _store(self, row: dict) -> dict:
        if self._table in ("conversations", "messages"):
            row.setdefault("id", str(uuid4()))
            row.setdefault("created_at", self._db.now())
        if self._table in ("conversations", "conversation_state"):
            row.setdefault("updated_at", self._db.now())
        self._db.tables[self._table].append(row)
        return row

    def _respond(self, rows: list[dict]):
        if self._columns != "*" and self._operation == "select":
            wanted = [c.strip() for c in self._columns.split(",")]
            rows = [{c: row.get(c) for c in wanted} for row in rows]
        return SimpleNamespace(data=[dict(row) for row in rows])
