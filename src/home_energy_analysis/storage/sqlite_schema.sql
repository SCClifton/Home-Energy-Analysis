CREATE TABLE IF NOT EXISTS prices (
    site_id TEXT NOT NULL,
    interval_start TEXT NOT NULL,
    interval_end TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    per_kwh REAL NOT NULL,
    renewables REAL,
    descriptor TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, interval_start, channel_type)
);

CREATE TABLE IF NOT EXISTS usage (
    site_id TEXT NOT NULL,
    interval_start TEXT NOT NULL,
    interval_end TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    kwh REAL NOT NULL,
    cost_aud REAL,
    quality TEXT,
    channel_identifier TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, interval_start, channel_type)
);

