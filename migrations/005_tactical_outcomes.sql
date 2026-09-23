CREATE TABLE IF NOT EXISTS eth_tactical_events (
    event_id TEXT PRIMARY KEY,
    event_version TEXT NOT NULL,
    nominal_time TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL,
    UNIQUE(event_version, nominal_time)
);

CREATE TABLE IF NOT EXISTS eth_tactical_outcomes (
    event_id TEXT NOT NULL REFERENCES eth_tactical_events(event_id),
    horizon_hours INTEGER NOT NULL CHECK (horizon_hours IN (1, 4, 12, 24)),
    settled_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL,
    PRIMARY KEY(event_id, horizon_hours)
);

CREATE INDEX IF NOT EXISTS idx_eth_tactical_events_nominal
    ON eth_tactical_events(nominal_time DESC);
CREATE INDEX IF NOT EXISTS idx_eth_tactical_outcomes_horizon
    ON eth_tactical_outcomes(horizon_hours, settled_at DESC);
