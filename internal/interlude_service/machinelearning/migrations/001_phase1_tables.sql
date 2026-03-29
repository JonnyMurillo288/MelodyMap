-- ================================================================
-- Phase 1 Migration: API Users, Usage Logging, Feedback, Caching
-- Run against musicbrainz_db
-- ================================================================

-- ---------------------------------------------------------------
-- API Users & Access Control
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    org_name TEXT,
    tier TEXT NOT NULL DEFAULT 'free',  -- 'free', 'researcher', 'enterprise'
    api_key_hash TEXT UNIQUE NOT NULL,
    rate_limit_per_hour INT NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_active TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS api_usage_log (
    log_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID REFERENCES api_users(user_id),
    endpoint TEXT NOT NULL,
    method TEXT NOT NULL,
    status_code INT,
    latency_ms FLOAT,
    request_params JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_user_date
    ON api_usage_log(user_id, created_at);

-- ---------------------------------------------------------------
-- User Feedback for Model Improvement (Strategy 4.2)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prediction_feedback (
    feedback_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID REFERENCES api_users(user_id),
    prediction_src INT NOT NULL,
    prediction_dst INT NOT NULL,
    model_id INT,
    rating INT CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- Daily Predictions Cache (for /trends/daily and Spotle)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_predictions (
    prediction_date DATE NOT NULL,
    genre TEXT NOT NULL,
    src_artist_id INT NOT NULL,
    src_artist_name TEXT,
    dst_artist_id INT NOT NULL,
    dst_artist_name TEXT,
    probability FLOAT,
    synthetic_track_ids INT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (prediction_date, genre, src_artist_id, dst_artist_id)
);

-- ---------------------------------------------------------------
-- What-If Scenario Cache
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenario_cache (
    cache_key TEXT PRIMARY KEY,  -- hash of (src, dst, constraints)
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days'
);

-- ---------------------------------------------------------------
-- Dataset Export Audit Trail
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dataset_exports (
    export_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES api_users(user_id),
    filters JSONB,
    row_count INT,
    file_format TEXT DEFAULT 'csv',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- Seed: Admin Test Account (full access, no rate limit)
-- API Key: interlude-test-key-do-not-share-2026
-- SHA-256 hash of that key is stored below
-- ---------------------------------------------------------------
INSERT INTO api_users (email, org_name, tier, api_key_hash, rate_limit_per_hour)
VALUES (
    'admin@interlude.local',
    'Interlude Dev',
    'enterprise',
    -- SHA-256 of 'interlude-test-key-do-not-share-2026'
    'ca85268cf81d0303a8a54fd0387a62b8ca0c5db9b4775bc5319a44399f9631db',
    999999
)
ON CONFLICT (email) DO UPDATE
SET tier = 'enterprise',
    rate_limit_per_hour = 999999;
