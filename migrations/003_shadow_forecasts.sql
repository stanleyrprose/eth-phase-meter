CREATE TABLE IF NOT EXISTS eth_forecasts (
    forecast_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mode TEXT NOT NULL,
    horizon TEXT NOT NULL,
    settled BOOLEAN NOT NULL DEFAULT FALSE,
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eth_forecasts_horizon_created ON eth_forecasts(horizon, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eth_forecasts_unsettled ON eth_forecasts(settled, created_at) WHERE settled = FALSE;
