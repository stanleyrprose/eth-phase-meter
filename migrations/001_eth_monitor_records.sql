CREATE TABLE IF NOT EXISTS eth_monitor_records (
    id BIGSERIAL PRIMARY KEY,
    record_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eth_monitor_records_type_time
    ON eth_monitor_records(record_type, created_at DESC);
