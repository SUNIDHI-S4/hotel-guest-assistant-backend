-- Adds the `timings` column to amenities on a database created before this change (schema.sql
-- and seed.sql already include it for a fresh setup, so this file is only for an existing one).
--
-- Run once in the Supabase SQL editor. It's safe to re-run: the ALTER is idempotent, and the
-- UPDATE only touches rows whose name matches one of the values below.

ALTER TABLE amenities ADD COLUMN IF NOT EXISTS timings TEXT;

UPDATE amenities a
SET timings = v.timings
FROM (VALUES
    ('Swimming Pool', '6:00 AM - 8:00 PM'),
    ('Gym', '5:00 AM - 10:00 PM'),
    ('Spa', '9:00 AM - 8:00 PM'),
    ('Restaurant', '7:00 AM - 11:00 PM'),
    ('Free WiFi', '24 hours'),
    ('Airport Shuttle', 'On request, 6:00 AM - 10:00 PM'),
    ('Coffee Plantation Tour', '10:00 AM and 4:00 PM daily'),
    ('Bonfire & Barbecue Area', '6:00 PM - 10:00 PM'),
    ('Indoor Games Room', '8:00 AM - 10:00 PM'),
    ('Conference Hall', '9:00 AM - 6:00 PM (by prior booking)')
) AS v(name, timings), hotels h
WHERE a.hotel_id = h.id AND a.name = v.name AND h.slug = 'the-clarks-inn-chikkamagaluru';

-- Verification
SELECT name, description, timings FROM amenities ORDER BY name;
