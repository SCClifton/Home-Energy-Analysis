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

CREATE TABLE IF NOT EXISTS irradiance (
    location_id TEXT NOT NULL,
    interval_start TEXT NOT NULL,
    interval_end TEXT NOT NULL,
    ghi_wm2 REAL NOT NULL,
    temperature_c REAL,
    cloud_cover_pct REAL,
    source TEXT NOT NULL DEFAULT 'open-meteo',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (location_id, interval_start)
);

CREATE TABLE IF NOT EXISTS simulation_intervals (
    scenario_id TEXT NOT NULL,
    controller_mode TEXT NOT NULL,
    interval_start TEXT NOT NULL,
    interval_end TEXT NOT NULL,
    baseline_import_kwh REAL NOT NULL,
    scenario_import_kwh REAL NOT NULL,
    battery_charge_kwh REAL NOT NULL,
    battery_discharge_kwh REAL NOT NULL,
    battery_soc_kwh REAL NOT NULL,
    pv_generation_kwh REAL NOT NULL,
    export_kwh REAL NOT NULL,
    baseline_cost_aud REAL NOT NULL,
    scenario_cost_aud REAL NOT NULL,
    savings_aud REAL NOT NULL,
    forecast INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scenario_id, controller_mode, interval_start)
);

CREATE INDEX IF NOT EXISTS idx_sim_intervals_lookup
    ON simulation_intervals (scenario_id, controller_mode, interval_start);

CREATE TABLE IF NOT EXISTS simulation_runs (
    scenario_id TEXT NOT NULL,
    controller_mode TEXT NOT NULL,
    run_mode TEXT NOT NULL,
    as_of TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    today_savings_aud REAL NOT NULL,
    mtd_savings_aud REAL NOT NULL,
    next_24h_projected_savings_aud REAL NOT NULL,
    current_battery_soc_kwh REAL NOT NULL,
    today_solar_generation_kwh REAL NOT NULL,
    today_export_revenue_aud REAL NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0,
    stale_reason TEXT,
    assumptions_json TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scenario_id, controller_mode, run_mode)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    analysis_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    data_quality_json TEXT NOT NULL,
    scenarios_json TEXT NOT NULL,
    recommendations_json TEXT NOT NULL,
    load_shift_json TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, year)
);
