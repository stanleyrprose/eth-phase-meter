from datetime import datetime, timedelta, timezone

import pytest

from eth_trend_v3.experiment_registry import RegistryValidationError, dataset_hash, validate_experiment
from eth_trend_v3.model_lifecycle import InvalidLifecycleTransition, transition
from eth_trend_v3.research_contract import ResearchSample
from eth_trend_v3.research_validation import purged_walk_forward

UTC = timezone.utc


def _row(i: int, label_hours: int = 12):
    t = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=4 * i)
    return {
        "feature_time": t.isoformat(),
        "available_at": t.isoformat(),
        "label_start_time": t.isoformat(),
        "label_end_time": (t + timedelta(hours=label_hours)).isoformat(),
        "horizon": "3d",
        "target_up": i % 2,
    }


def test_research_sample_rejects_future_unavailable_label_start():
    t = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        ResearchSample(t, t + timedelta(hours=1), t, t + timedelta(days=3), "3d")


def test_purged_walk_forward_removes_overlapping_training_labels():
    rows = [_row(i, label_hours=12) for i in range(12)]
    folds = purged_walk_forward(rows, min_train=6, test_size=3)
    first = folds[0]
    boundary = datetime.fromisoformat(first["report"]["test_start"])
    assert first["report"]["purged_count"] > 0
    assert all(datetime.fromisoformat(r["label_end_time"]) < boundary for r in first["train"])


def test_embargo_is_separate_from_purge():
    rows = [_row(i, label_hours=4) for i in range(12)]
    no_gap = purged_walk_forward(rows, min_train=6, test_size=3, embargo_hours=0)[0]
    gap = purged_walk_forward(rows, min_train=6, test_size=3, embargo_hours=8)[0]
    assert gap["report"]["purged_count"] == no_gap["report"]["purged_count"]
    assert gap["report"]["embargo_removed_count"] >= 1
    assert gap["report"]["train_after"] < no_gap["report"]["train_after"]


def test_dataset_hash_is_order_sensitive_and_stable():
    rows = [{"a": 1}, {"a": 2}]
    assert dataset_hash(rows) == dataset_hash(rows)
    assert dataset_hash(rows) != dataset_hash(list(reversed(rows)))


def test_registry_requires_critical_fields():
    with pytest.raises(RegistryValidationError):
        validate_experiment({"experiment_id": "x"})


def test_lifecycle_blocks_experimental_to_production():
    with pytest.raises(InvalidLifecycleTransition):
        transition("EXPERIMENTAL", "PRODUCTION", reason="skip")


def test_lifecycle_allows_candidate_to_shadow():
    event = transition("CANDIDATE", "SHADOW", reason="research gate passed")
    assert event.to_state == "SHADOW"
