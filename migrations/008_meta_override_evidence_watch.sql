CREATE TABLE IF NOT EXISTS eth_meta_override_evidence_watch (
    watch_key TEXT PRIMARY KEY,
    last_notified_checkpoint INTEGER NOT NULL DEFAULT 0 CHECK (last_notified_checkpoint >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
