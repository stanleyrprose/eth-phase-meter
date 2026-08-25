from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

CRITICAL_FIELDS = (
    "experiment_id", "git_sha", "workflow_version", "dataset_version", "dataset_hash",
    "feature_version", "label_version", "horizon", "validation_method", "model_type",
    "model_config", "random_seed", "gate_version", "candidate_count", "status",
)


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


def validate_experiment(record: Mapping[str, Any], *, require_critical: bool = True) -> None:
    if not require_critical:
        return
    missing = [k for k in CRITICAL_FIELDS if record.get(k) is None or record.get(k) == ""]
    if missing:
        raise RegistryValidationError("missing critical experiment fields: " + ", ".join(missing))


def persist_experiment(record: Mapping[str, Any], artifact_dir: str = "eth_reports/experiments") -> str:
    data = dict(record)
    data.setdefault("experiment_id", new_experiment_id())
    data.setdefault("created_at", datetime.now(timezone.utc).isoformat())
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
