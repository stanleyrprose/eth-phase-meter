CREATE TABLE IF NOT EXISTS eth_model_governance_log (
    event_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eth_model_governance_log_type_created
    ON eth_model_governance_log(event_type, created_at DESC);
