-- Supabase Postgres schema for home energy analysis data
-- Run this in the Supabase SQL editor to create the tables

-- Enable pgcrypto extension for UUID generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Ingest events table: tracks raw API responses and ingestion metadata
CREATE TABLE IF NOT EXISTS ingest_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,  -- e.g., 'amber', 'powerpal', 'powerpow'
    kind TEXT NOT NULL,    -- e.g., 'prices', 'usage'
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    payload_hash TEXT NOT NULL,  -- SHA256 hash of canonical JSON payload
    payload JSONB,               -- Full raw payload for debugging/audit
    status TEXT NOT NULL DEFAULT 'ok',  -- 'ok', 'error', 'partial'
    error TEXT                    -- Error message if status != 'ok'
);

-- Unique index to prevent duplicate ingestions
CREATE UNIQUE INDEX IF NOT EXISTS idx_ingest_events_unique 
    ON ingest_events(source, kind, payload_hash);

-- Index for querying by time window
CREATE INDEX IF NOT EXISTS idx_ingest_events_window 
    ON ingest_events(window_start, window_end);

-- Price intervals table: stores wholesale price data
CREATE TABLE IF NOT EXISTS price_intervals (
    site_id TEXT NOT NULL,
    interval_start TIMESTAMPTZ NOT NULL,
    interval_end TIMESTAMPTZ NOT NULL,
    is_forecast BOOLEAN NOT NULL DEFAULT FALSE,
    price_cents_per_kwh NUMERIC(10, 4),
    spot_per_kwh NUMERIC(10, 4),
    descriptor TEXT,
    spike_status TEXT,
    renewables_percent NUMERIC(5, 2),
    source TEXT NOT NULL DEFAULT 'amber',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_event_id UUID REFERENCES ingest_events(id),
    PRIMARY KEY (site_id, interval_start, is_forecast, source)
);

-- Index for time-based queries
CREATE INDEX IF NOT EXISTS idx_price_intervals_time 
    ON price_intervals(interval_start, interval_end);

-- Index for forecast queries
CREATE INDEX IF NOT EXISTS idx_price_intervals_forecast 
    ON price_intervals(is_forecast, interval_start);

-- Usage intervals table: stores energy consumption data
CREATE TABLE IF NOT EXISTS usage_intervals (
    site_id TEXT NOT NULL,
    channel_type TEXT NOT NULL DEFAULT 'general',
    interval_start TIMESTAMPTZ NOT NULL,
    interval_end TIMESTAMPTZ NOT NULL,
    kwh NUMERIC(10, 6) NOT NULL,
    cost_aud NUMERIC(10, 4),
    quality TEXT,
    meter_identifier TEXT,
    source TEXT NOT NULL DEFAULT 'amber',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_event_id UUID REFERENCES ingest_events(id),
    PRIMARY KEY (site_id, channel_type, interval_start, source)
);

-- Index for time-based queries
CREATE INDEX IF NOT EXISTS idx_usage_intervals_time 
    ON usage_intervals(interval_start, interval_end);

-- Index for channel type queries
CREATE INDEX IF NOT EXISTS idx_usage_intervals_channel 
    ON usage_intervals(channel_type, interval_start);

