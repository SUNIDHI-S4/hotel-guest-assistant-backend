-- Hotel Guest Assistant - database schema (Supabase PostgreSQL)
-- Run this first in the Supabase SQL editor, then run seed.sql.
--
-- NOTE: conversations, messages and conversation_state are not defined in the
-- original setup guide. Their column names match the live database; the types and
-- constraints below are reconstructed to fit how the app uses them.

-- ---------------------------------------------------------------------------
-- Hotel knowledge base
-- ---------------------------------------------------------------------------

CREATE TABLE hotels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    country VARCHAR(100),
    check_in_time TIME NOT NULL,
    check_out_time TIME NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE amenities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hotel_id UUID NOT NULL REFERENCES hotels(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    -- Free text: an hour range ("6:00 AM - 8:00 PM"), fixed slots ("10 AM and 4 PM daily") or
    -- "24 hours" don't fit one rigid format. NULL means no fixed timing (e.g. always available).
    timings TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hotel_id UUID NOT NULL REFERENCES hotels(id),
    policy_type VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE room_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hotel_id UUID NOT NULL REFERENCES hotels(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    max_guests INTEGER NOT NULL,
    price_per_night DECIMAL(10,2) NOT NULL,
    breakfast_included BOOLEAN DEFAULT FALSE,
    total_rooms INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Used for availability calculations.
CREATE TABLE bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hotel_id UUID NOT NULL REFERENCES hotels(id),
    room_type_id UUID NOT NULL REFERENCES room_types(id),
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    guest_count INTEGER NOT NULL,
    booking_status VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Conversation persistence
-- ---------------------------------------------------------------------------

CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hotel_id UUID NOT NULL REFERENCES hotels(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Availability slot tracking: one row per conversation, slots stay NULL until collected.
CREATE TABLE conversation_state (
    conversation_id UUID PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    check_in DATE,
    check_out DATE,
    guest_count INTEGER,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX idx_bookings_room_type
ON bookings(room_type_id);

CREATE INDEX idx_bookings_dates
ON bookings(check_in_date, check_out_date);

CREATE INDEX idx_messages_conversation
ON messages(conversation_id);

-- ---------------------------------------------------------------------------
-- Row level security
-- Disabled because only the backend talks to the database (the key never reaches
-- the browser). Enable RLS and use a service_role key before production.
-- ---------------------------------------------------------------------------

ALTER TABLE hotels DISABLE ROW LEVEL SECURITY;
ALTER TABLE amenities DISABLE ROW LEVEL SECURITY;
ALTER TABLE policies DISABLE ROW LEVEL SECURITY;
ALTER TABLE room_types DISABLE ROW LEVEL SECURITY;
ALTER TABLE bookings DISABLE ROW LEVEL SECURITY;
ALTER TABLE conversations DISABLE ROW LEVEL SECURITY;
ALTER TABLE messages DISABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_state DISABLE ROW LEVEL SECURITY;
