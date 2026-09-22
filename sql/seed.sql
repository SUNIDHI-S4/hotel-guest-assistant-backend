-- Hotel Guest Assistant - seed data
-- Run after schema.sql. Rows reference the hotel by slug and rooms by name, so no IDs
-- need to be copied by hand. Afterwards, run `SELECT id FROM hotels;` and put that
-- value in DEFAULT_HOTEL_ID in the backend .env file.

INSERT INTO hotels (
    slug, name, description, address, city, state, country,
    check_in_time, check_out_time
)
VALUES (
    'royal-orchid-bengaluru',
    'Royal Orchid Bengaluru',
    'A premier business and leisure hotel in the heart of Bengaluru, offering modern comfort and warm hospitality.',
    '47 MG Road',
    'Bengaluru',
    'Karnataka',
    'India',
    '15:00',
    '11:00'
);

INSERT INTO amenities (hotel_id, name, description)
SELECT h.id, a.name, a.description
FROM hotels h,
(VALUES
    ('Swimming Pool', 'Outdoor swimming pool with a landscaped sundeck'),
    ('Gym', 'Fully equipped fitness center'),
    ('Spa', 'Wellness and spa treatments available'),
    ('Restaurant', 'Multi-cuisine restaurant serving breakfast, lunch and dinner'),
    ('Free WiFi', 'High-speed wireless internet throughout the property'),
    ('Airport Shuttle', 'Paid airport pickup and drop service')
) AS a(name, description)
WHERE h.slug = 'royal-orchid-bengaluru';

INSERT INTO policies (hotel_id, policy_type, content)
SELECT h.id, p.policy_type, p.content
FROM hotels h,
(VALUES
    ('cancellation', 'Free cancellation up to 24 hours before check-in.'),
    ('pets', 'Pets are not allowed at the property.'),
    ('parking', 'Complimentary on-site parking is available for guests.'),
    ('breakfast', 'Complimentary breakfast is included for selected room types.')
) AS p(policy_type, content)
WHERE h.slug = 'royal-orchid-bengaluru';

INSERT INTO room_types (
    hotel_id, name, description, max_guests,
    price_per_night, breakfast_included, total_rooms
)
SELECT h.id, r.name, r.description, r.max_guests, r.price_per_night, r.breakfast_included, r.total_rooms
FROM hotels h,
(VALUES
    ('Deluxe Room', 'Comfortable room with garden view.', 2, 4500, true, 10),
    ('Family Suite', 'Spacious suite suitable for families.', 4, 8500, true, 5),
    ('Executive Suite', 'Premium suite with city view and lounge access.', 5, 12000, true, 3)
) AS r(name, description, max_guests, price_per_night, breakfast_included, total_rooms)
WHERE h.slug = 'royal-orchid-bengaluru';

-- Sample bookings so availability checks have something to overlap with.
INSERT INTO bookings (
    hotel_id, room_type_id, check_in_date,
    check_out_date, guest_count, booking_status
)
SELECT rt.hotel_id, rt.id, b.check_in_date::date, b.check_out_date::date, b.guest_count, 'confirmed'
FROM room_types rt
JOIN (VALUES
    ('Deluxe Room', '2026-10-18', '2026-10-21', 2),
    ('Family Suite', '2026-10-20', '2026-10-22', 3),
    ('Family Suite', '2026-10-21', '2026-10-24', 4),
    ('Executive Suite', '2026-10-25', '2026-10-28', 4)
) AS b(room_name, check_in_date, check_out_date, guest_count)
    ON rt.name = b.room_name
JOIN hotels h ON h.id = rt.hotel_id AND h.slug = 'royal-orchid-bengaluru';

-- Verification
SELECT * FROM hotels;
SELECT * FROM amenities;
SELECT * FROM policies;
SELECT * FROM room_types;
SELECT * FROM bookings;
