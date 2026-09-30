CREATE TABLE IF NOT EXISTS eth_meta_action_outcome_revisions (
    event_id TEXT NOT NULL,
    horizon_hours INTEGER NOT NULL CHECK (horizon_hours IN (4, 12, 24, 72)),
    revision INTEGER NOT NULL CHECK (revision > 0),
    correction_reason TEXT NOT NULL,
    source_git_sha TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL,
    PRIMARY KEY(event_id, horizon_hours, revision),
    FOREIGN KEY(event_id, horizon_hours)
        REFERENCES eth_meta_action_outcomes(event_id, horizon_hours)
);

CREATE INDEX IF NOT EXISTS idx_eth_meta_action_outcome_revisions_latest
    ON eth_meta_action_outcome_revisions(event_id, horizon_hours, revision DESC);
