from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class ResearchInvalid(RuntimeError):
    """Raised when a research run violates a hard validity rule."""


class ModelStatus(str, Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    PRODUCTION = "PRODUCTION"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"
    DESCRIPTIVE_PRODUCTION = "DESCRIPTIVE_PRODUCTION"


_ALLOWED_TRANSITIONS = {
    ModelStatus.EXPERIMENTAL: {ModelStatus.CANDIDATE, ModelStatus.RETIRED, ModelStatus.DESCRIPTIVE_PRODUCTION},
    ModelStatus.CANDIDATE: {ModelStatus.SHADOW, ModelStatus.RETIRED},
    ModelStatus.SHADOW: {ModelStatus.PRODUCTION, ModelStatus.CANDIDATE, ModelStatus.RETIRED},
    ModelStatus.PRODUCTION: {ModelStatus.DEGRADED, ModelStatus.SHADOW, ModelStatus.RETIRED},
    ModelStatus.DEGRADED: {ModelStatus.SHADOW, ModelStatus.CANDIDATE, ModelStatus.RETIRED},
    ModelStatus.DESCRIPTIVE_PRODUCTION: {ModelStatus.RETIRED},
    ModelStatus.RETIRED: set(),
}


@dataclass(frozen=True)
class ResearchSample:
    feature_time: datetime
    available_at: datetime
    label_start_time: datetime
    label_end_time: datetime
    horizon: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        vals = (self.feature_time, self.available_at, self.label_start_time, self.label_end_time)
        if any(v.tzinfo is None for v in vals):
            raise ValueError("research timestamps must be timezone-aware")
        if self.available_at < self.feature_time:
            raise ValueError("available_at cannot precede feature_time")
        if self.label_start_time < self.available_at:
            raise ResearchInvalid("label_start_time precedes feature availability")
        if self.label_end_time <= self.label_start_time:
            raise ValueError("label_end_time must be after label_start_time")


@dataclass(frozen=True)
class Fold:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    purged_count: int
    embargo_removed_count: int
    test_start: datetime
    test_end: datetime


def _to_hours(horizon: str) -> int:
    mapping = {"3d": 72, "7d": 168, "30d": 720}
    try:
        return mapping[horizon.lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported horizon: {horizon}") from exc


def purged_walk_forward(
    samples: Sequence[ResearchSample],
    *,
    min_train: int,
    test_size: int,
    embargo_multiplier: float = 1.0,
) -> list[Fold]:
    """Expanding walk-forward with explicit label purging and pre-test embargo."""
    if min_train <= 0 or test_size <= 0:
        raise ValueError("min_train/test_size must be positive")
    if embargo_multiplier < 0:
        raise ValueError("embargo_multiplier must be non-negative")
    ordered = sorted(enumerate(samples), key=lambda kv: kv[1].available_at)
    folds: list[Fold] = []
    for start in range(min_train, len(ordered), test_size):
        test_slice = ordered[start : start + test_size]
        if not test_slice:
            continue
        test_start = test_slice[0][1].available_at
        test_end = test_slice[-1][1].label_end_time
        horizon_hours = _to_hours(test_slice[0][1].horizon)
        embargo_start = test_start - timedelta(hours=horizon_hours * embargo_multiplier)

        train: list[int] = []
        purged = 0
        embargoed = 0
        for original_idx, sample in ordered[:start]:
            if sample.label_end_time >= test_start:
                purged += 1
                continue
            if sample.available_at >= embargo_start:
                embargoed += 1
                continue
            train.append(original_idx)

        if not train:
            continue
        folds.append(
            Fold(
                train_indices=tuple(train),
                test_indices=tuple(i for i, _ in test_slice),
                purged_count=purged,
                embargo_removed_count=embargoed,
                test_start=test_start,
                test_end=test_end,
            )
        )
    return folds


def assert_no_label_leakage(samples: Sequence[ResearchSample], fold: Fold) -> None:
    for idx in fold.train_indices:
        if samples[idx].label_end_time >= fold.test_start:
            raise ResearchInvalid("label leakage detected in training fold")


def content_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    """Stable SHA-256 over JSON-serializable research rows."""
    h = hashlib.sha256()
    for row in rows:
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode()
        h.update(encoded)
        h.update(b"\n")
    return h.hexdigest()


CRITICAL_EXPERIMENT_FIELDS = {
    "experiment_id",
    "git_sha",
    "workflow_version",
    "dataset_version",
    "dataset_hash",
    "feature_version",
    "label_version",
    "horizon",
    "validation_method",
    "purge_config",
    "embargo_config",
    "model_type",
    "model_config",
    "random_seed",
    "gate_version",
    "candidate_count",
    "status",
    "created_at",
}


def validate_experiment_record(record: Mapping[str, Any]) -> None:
    missing = sorted(k for k in CRITICAL_EXPERIMENT_FIELDS if record.get(k) in (None, ""))
    if missing:
        raise ResearchInvalid("registry incomplete: " + ", ".join(missing))
    if len(str(record["dataset_hash"])) < 32:
        raise ResearchInvalid("dataset_hash is not a content hash")


class ExperimentRegistry:
    """Append-only artifact registry with optional PostgreSQL mirroring."""

    def __init__(self, artifact_path: str | Path, database_url: str | None = None):
        self.artifact_path = Path(artifact_path)
        self.database_url = database_url

    def append(self, record: Mapping[str, Any]) -> None:
        validate_experiment_record(record)
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        with self.artifact_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(record), sort_keys=True, default=str) + "\n")
        if self.database_url:
            self._append_postgres(record)

    def _append_postgres(self, record: Mapping[str, Any]) -> None:
        import psycopg

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forecast_experiments (
                        experiment_id TEXT PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL,
                        status TEXT NOT NULL,
                        git_sha TEXT NOT NULL,
                        dataset_hash TEXT NOT NULL,
                        payload JSONB NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    INSERT INTO forecast_experiments
                        (experiment_id, created_at, status, git_sha, dataset_hash, payload)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (experiment_id) DO NOTHING
                    """,
                    (
                        record["experiment_id"],
                        record["created_at"],
                        record["status"],
                        record["git_sha"],
                        record["dataset_hash"],
                        json.dumps(dict(record), default=str),
                    ),
                )
            conn.commit()


def transition_model(
    current: ModelStatus,
    target: ModelStatus,
    *,
    reason: str,
    trigger: str,
    operator_or_system: str,
    gate_version: str,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ResearchInvalid(f"illegal lifecycle transition: {current.value} -> {target.value}")
    ts = timestamp or datetime.now(timezone.utc)
    return {
        "from_state": current.value,
        "to_state": target.value,
        "reason": reason,
        "trigger": trigger,
        "operator_or_system": operator_or_system,
        "timestamp": ts.isoformat(),
        "gate_version": gate_version,
    }


def build_run_manifest(
    *,
    run_id: str,
    git_sha: str,
    workflow_name: str,
    python_version: str,
    dependency_hash: str,
    dataset_hash: str,
    experiment_ids: Sequence[str],
    artifacts: Sequence[str],
    result: str,
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "git_sha": git_sha,
        "workflow_name": workflow_name,
        "python_version": python_version,
        "dependency_hash": dependency_hash,
        "dataset_hash": dataset_hash,
        "experiment_ids": list(experiment_ids),
        "artifacts": list(artifacts),
        "result": result,
        "started_at": started_at,
        "completed_at": completed_at,
    }
