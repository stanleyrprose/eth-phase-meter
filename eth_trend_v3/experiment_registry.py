from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

BASE_CRITICAL_FIELDS = (
    "experiment_id", "experiment_family", "git_sha", "workflow_version", "schema_version",
    "dataset_version", "dataset_hash", "config_hash", "feature_set", "feature_version",
    "label_version", "horizon", "validation_method", "purge_config", "embargo_config",
    "model_type", "model_config", "random_seed", "gate_version", "candidate_count",
    "feature_variants_tested", "models_tested", "parameters_tested",
    "interaction_variants_tested", "holdout_status", "status",
)

PROMOTION_CRITICAL_FIELDS = BASE_CRITICAL_FIELDS + (
    "model_artifact_hash", "data_start", "data_end", "train_windows", "test_windows",
    "brier", "brier_skill_score", "log_loss", "calibration_error", "raw_oos_n",
    "effective_sample_diagnostic", "bootstrap_method", "bootstrap_ci", "fold_metrics",
    "promotion_gate_result", "model_status",
)

# Backward-compatible export used by older callers/tests.
CRITICAL_FIELDS = BASE_CRITICAL_FIELDS


class RegistryValidationError(ValueError):
    pass


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dataset_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    return stable_hash(list(rows))


def new_experiment_id(prefix: str = "exp") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid4().hex[:10]}"


def experiment_config_hash(record: Mapping[str, Any]) -> str:
    return stable_hash({
        "model_config": record.get("model_config"),
        "feature_set": record.get("feature_set"),
        "purge_config": record.get("purge_config"),
        "embargo_config": record.get("embargo_config"),
        "gate_version": record.get("gate_version"),
        "validation_method": record.get("validation_method"),
    })


def validate_experiment(
    record: Mapping[str, Any],
    *,
    require_critical: bool = True,
    for_promotion: bool = False,
) -> None:
    if not require_critical:
        return
    fields = PROMOTION_CRITICAL_FIELDS if for_promotion else BASE_CRITICAL_FIELDS
    missing = [k for k in fields if record.get(k) is None or record.get(k) == ""]
    if missing:
        raise RegistryValidationError("missing critical experiment fields: " + ", ".join(missing))
    expected = experiment_config_hash(record)
    if record.get("config_hash") != expected:
        raise RegistryValidationError("config_hash mismatch")
    if str(record.get("holdout_status")).upper() == "CONTAMINATED" and for_promotion:
        raise RegistryValidationError("holdout contaminated")


def persist_experiment(record: Mapping[str, Any], artifact_dir: str = "eth_reports/experiments") -> str:
    data = dict(record)
    data.setdefault("experiment_id", new_experiment_id())
    data.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    data.setdefault("config_hash", experiment_config_hash(data))
    validate_experiment(data)

    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS eth_experiment_registry (
                        experiment_id TEXT PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        status TEXT NOT NULL,
                        git_sha TEXT NOT NULL,
                        dataset_hash TEXT NOT NULL,
                        payload JSONB NOT NULL
                    )
                """)
                cur.execute("""
                    INSERT INTO eth_experiment_registry(experiment_id,status,git_sha,dataset_hash,payload)
                    VALUES (%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (experiment_id) DO UPDATE SET
                    status=EXCLUDED.status, git_sha=EXCLUDED.git_sha,
                    dataset_hash=EXCLUDED.dataset_hash, payload=EXCLUDED.payload
                """, (data["experiment_id"], data["status"], data["git_sha"], data["dataset_hash"], json.dumps(data, default=str)))
            conn.commit()
    else:
        root = Path(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{data['experiment_id']}.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data["experiment_id"]


def load_experiment(experiment_id: str, artifact_dir: str = "eth_reports/experiments") -> dict | None:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM eth_experiment_registry WHERE experiment_id=%s", (experiment_id,))
                row = cur.fetchone()
                return row[0] if row else None
    path = Path(artifact_dir) / f"{experiment_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
