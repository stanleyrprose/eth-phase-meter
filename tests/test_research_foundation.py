from datetime import datetime, timedelta, timezone
import json

import pytest

from eth_trend_v3.research_foundation import (
    ExperimentRegistry,
    ModelStatus,
    ResearchInvalid,
    ResearchSample,
    assert_no_label_leakage,
    content_hash,
    purged_walk_forward,
    transition_model,
    validate_experiment_record,
)

UTC = timezone.utc


def sample(i: int, horizon="3d") -> ResearchSample:
    t = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)
    hours = {"3d": 72, "7d": 168, "30d": 720}[horizon]
    return ResearchSample(
        feature_time=t,
        available_at=t,
        label_start_time=t + timedelta(seconds=1),
        label_end_time=t + timedelta(hours=hours),
        horizon=horizon,
        payload={"i": i},
    )


def test_research_sample_rejects_future_information_overlap():
    t = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ResearchInvalid):
        ResearchSample(t, t + timedelta(hours=1), t, t + timedelta(days=3), "3d", {})


def test_purge_boundary_and_embargo_are_separate():
    rows = [sample(i) for i in range(12)]
    folds = purged_walk_forward(rows, min_train=8, test_size=2, embargo_multiplier=1.0)
    assert folds
    first = folds[0]
    assert first.purged_count > 0
    assert first.embargo_removed_count >= 0
    assert all(rows[i].label_end_time < first.test_start for i in first.train_indices)
    assert_no_label_leakage(rows, first)


def test_embargo_multiplier_changes_train_size_not_purge_definition():
    rows = [sample(i) for i in range(20)]
    a = purged_walk_forward(rows, min_train=12, test_size=2, embargo_multiplier=0.0)[0]
    b = purged_walk_forward(rows, min_train=12, test_size=2, embargo_multiplier=1.5)[0]
    assert a.purged_count == b.purged_count
    assert len(b.train_indices) <= len(a.train_indices)


def valid_record():
    return {
        "experiment_id": "exp-1",
        "git_sha": "abc123",
        "workflow_version": "v1",
        "dataset_version": "v1",
        "dataset_hash": "a" * 64,
        "feature_version": "v1",
        "label_version": "v1",
        "horizon": "3d",
        "validation_method": "purged_walk_forward",
        "purge_config": {"enabled": True},
        "embargo_config": {"multiplier": 1.0},
        "model_type": "baseline",
        "model_config": {},
        "random_seed": 42,
        "gate_version": "research-v1",
        "candidate_count": 1,
        "status": "EXPERIMENTAL",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_registry_schema_is_enforced(tmp_path):
    rec = valid_record()
    validate_experiment_record(rec)
    bad = dict(rec)
    bad.pop("dataset_hash")
    with pytest.raises(ResearchInvalid):
        validate_experiment_record(bad)
    path = tmp_path / "registry.jsonl"
    ExperimentRegistry(path).append(rec)
    saved = json.loads(path.read_text().splitlines()[0])
    assert saved["experiment_id"] == "exp-1"


def test_dataset_hash_is_order_sensitive_and_deterministic():
    rows = [{"a": 1}, {"a": 2}]
    assert content_hash(rows) == content_hash(rows)
    assert content_hash(rows) != content_hash(list(reversed(rows)))


def test_illegal_lifecycle_jump_is_blocked():
    with pytest.raises(ResearchInvalid):
        transition_model(ModelStatus.EXPERIMENTAL, ModelStatus.PRODUCTION, reason="skip", trigger="manual", operator_or_system="test", gate_version="v1")


def test_valid_lifecycle_transition_has_audit_fields():
    event = transition_model(ModelStatus.CANDIDATE, ModelStatus.SHADOW, reason="research gate passed", trigger="system", operator_or_system="github-actions", gate_version="v1")
    assert event["from_state"] == "CANDIDATE"
    assert event["to_state"] == "SHADOW"
    assert event["timestamp"]
