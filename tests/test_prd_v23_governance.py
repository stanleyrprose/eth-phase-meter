from __future__ import annotations

import json

import pytest

from eth_trend_v3.experiment_registry import (
    RegistryValidationError,
    experiment_config_hash,
    validate_experiment,
)
from eth_trend_v3.governance import (
    GateVersionConflict,
    mark_holdout_contaminated,
    mark_holdout_viewed,
    register_gate_version,
    register_holdout,
)
from eth_trend_v3.model_artifact import ModelArtifactError, build_model_artifact, infer_model_artifact
from eth_trend_v3.model_state import initialize_model_state
from eth_trend_v3.promotion import promotion_gate


def _experiment(**patch):
    record = {
        "experiment_id": "exp-1",
        "experiment_family": "family-1",
        "git_sha": "abc123",
        "workflow_version": "wf-v1",
        "schema_version": "registry-v2.3",
        "dataset_version": "dataset-v1",
        "dataset_hash": "dataset-hash",
        "feature_set": ["trend"],
        "feature_version": "feature-v1",
        "label_version": "label-v1",
        "horizon": "3d",
        "validation_method": "purged-walk-forward",
        "purge_config": {"enabled": True},
        "embargo_config": {"hours": 36},
        "model_type": "logistic",
        "model_config": {"C": 1.0},
        "random_seed": 0,
        "gate_version": "gate-v1",
        "candidate_count": 3,
        "feature_variants_tested": 2,
        "models_tested": 3,
        "parameters_tested": 1,
        "interaction_variants_tested": 0,
        "holdout_status": "NEVER_TOUCHED",
        "status": "CANDIDATE",
    }
    record.update(patch)
    record["config_hash"] = experiment_config_hash(record)
    return record


def test_registry_full_contract_and_promotion_fields_are_enforced():
    record = _experiment()
    validate_experiment(record)
    with pytest.raises(RegistryValidationError):
        validate_experiment(record, for_promotion=True)
    promotion = {
        **record,
        "model_artifact_hash": "artifact",
        "data_start": "2025-01-01T00:00:00Z",
        "data_end": "2026-01-01T00:00:00Z",
        "train_windows": [{"start": "a", "end": "b"}],
        "test_windows": [{"start": "c", "end": "d"}],
        "brier": 0.20,
        "brier_skill_score": 0.03,
        "log_loss": 0.60,
        "calibration_error": 0.05,
        "raw_oos_n": 100,
        "effective_sample_diagnostic": {"kind": "DIAGNOSTIC", "value": 20},
        "bootstrap_method": "moving-block",
        "bootstrap_ci": [0.001, 0.04],
        "fold_metrics": [{"brier": 0.2}],
        "promotion_gate_result": "PASS",
        "model_status": "SHADOW",
    }
    validate_experiment(promotion, for_promotion=True)
    promotion["holdout_status"] = "CONTAMINATED"
    promotion["config_hash"] = experiment_config_hash(promotion)
    with pytest.raises(RegistryValidationError):
        validate_experiment(promotion, for_promotion=True)


def test_gate_version_is_immutable_and_holdout_contamination_is_persistent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = register_gate_version("gate-v1", {"min_bss": 0.01})
    assert register_gate_version("gate-v1", {"min_bss": 0.01})["gate_hash"] == first["gate_hash"]
    with pytest.raises(GateVersionConflict):
        register_gate_version("gate-v1", {"min_bss": -0.01})

    holdout = register_holdout("family-1", "2025-01-01", "2025-12-31")
    assert holdout["status"] == "NEVER_TOUCHED"
    assert mark_holdout_viewed("family-1")["status"] == "CONSUMED"
    contaminated = mark_holdout_contaminated("family-1", reason="feature changed after viewing")
    assert contaminated["status"] == "CONTAMINATED"


def test_promotion_gate_requires_clean_holdout():
    evidence = {
        "leakage_free": True,
        "pit_valid": True,
        "registry_complete": True,
        "artifact_valid": True,
        "train_serve_parity": True,
        "shadow_complete": True,
        "data_health_normal": True,
        "emergency_freeze_clear": True,
        "holdout_clean": False,
        "effective_shadow_confirmed": True,
        "research_brier_skill": 0.03,
        "shadow_brier_skill": 0.02,
        "calibration_error": 0.05,
    }
    decision = promotion_gate(evidence)
    assert not decision.eligible
    assert "HOLDOUT_CONTAMINATED" in decision.reasons


def test_frozen_model_artifact_hash_and_inference_contract_are_enforced():
    logistic = {
        "features": ["trend"],
        "mean": [0.0],
        "scale": [1.0],
        "coef": [1.0],
        "intercept": 0.0,
        "interactions": [],
        "model_type": "logistic",
    }
    artifact = build_model_artifact(
        model_id="m1",
        model_version="v1",
        experiment_id="exp-1",
        horizon="3d",
        git_sha="abc",
        dataset_hash="data",
        config_hash="cfg",
        gate_version="gate-v1",
        baseline_spec={"name": "expanding"},
        base_features=["trend"],
        logistic_artifact=logistic,
    )
    assert infer_model_artifact(artifact, {"trend": 1.0}) > 0.5
    tampered = json.loads(json.dumps(artifact))
    tampered["logistic_artifact"]["coef"] = [99.0]
    with pytest.raises(ModelArtifactError):
        infer_model_artifact(tampered, {"trend": 1.0})


def test_model_state_cannot_initialize_directly_as_shadow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        initialize_model_state(
            horizon="3d", status="SHADOW", model_id="m", model_version="v",
            artifact_hash="a", experiment_id="e", gate_version="g",
        )
