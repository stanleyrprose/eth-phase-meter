CREATE TABLE IF NOT EXISTS eth_model_artifacts (
    artifact_hash TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    horizon TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eth_model_artifacts_horizon_created
    ON eth_model_artifacts(horizon, created_at DESC);

CREATE TABLE IF NOT EXISTS eth_research_gate_versions (
    gate_version TEXT PRIMARY KEY,
    gate_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS eth_holdout_registry (
    experiment_family TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS eth_override_log (
    override_id TEXT PRIMARY KEY,
    horizon TEXT NOT NULL,
    action TEXT NOT NULL,
    operator_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eth_override_log_horizon_created
    ON eth_override_log(horizon, created_at DESC);

CREATE TABLE IF NOT EXISTS eth_model_control_state (
    horizon TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS eth_model_states (
    horizon TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL
);
