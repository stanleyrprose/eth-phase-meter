CREATE TABLE IF NOT EXISTS eth_experiment_registry (
    experiment_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL,
    git_sha TEXT NOT NULL,
    dataset_hash TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS eth_model_transition_log (
    id BIGSERIAL PRIMARY KEY,
    model_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    trigger TEXT NOT NULL,
    operator_or_system TEXT NOT NULL,
    gate_version TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_eth_experiment_registry_created_at
    ON eth_experiment_registry(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eth_model_transition_log_model_id
    ON eth_model_transition_log(model_id, created_at DESC);
