from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Any, Mapping

from .experiment_registry import stable_hash
from .persistence import load_latest_record, persist_json_record

from .reason_codes import UNAVAILABLE_REASONS
from .experiment_registry import load_experiment, validate_experiment
from .governance import publication_allowed, record_override, register_gate_version
from .model_artifact import load_model_artifact
from .model_state import current_model_state, persist_model_state, transition_model



@dataclass(frozen=True)
class GateConfig:
    version: str = "v1"
    min_research_brier_skill: float = 0.0
    min_shadow_brier_skill: float = 0.0
    max_calibration_error: float = 0.10
    require_effective_shadow_evidence: bool = True

    @property
    def config_hash(self) -> str:
        return stable_hash(asdict(self))


@dataclass(frozen=True)
class GateDecision:
    eligible: bool
    status: str
    reasons: list[str]
    gate_version: str
    gate_hash: str

    def to_dict(self):
        return asdict(self)


def promotion_gate(
    evidence: Mapping[str, Any],
    *,
    gate: GateConfig | None = None,
    gate_version: str | None = None,
) -> GateDecision:
    gate = gate or GateConfig(version=gate_version or "v1")
    reasons = []
    hard = {
        "leakage_free": "LEAKAGE_DETECTED",
        "pit_valid": "SOURCE_CONTRACT_FAILED",
        "registry_complete": "REGISTRY_INCOMPLETE",
        "artifact_valid": "MODEL_ARTIFACT_MISSING",
        "train_serve_parity": "TRAIN_SERVE_SKEW",
        "shadow_complete": "SHADOW_INSUFFICIENT",
        "data_health_normal": "DATA_HEALTH_CRITICAL",
        "emergency_freeze_clear": "EMERGENCY_FREEZE",
        "holdout_clean": "HOLDOUT_CONTAMINATED",
    }
    for key, reason in hard.items():
        if not bool(evidence.get(key)):
            reasons.append(reason)
    if gate.require_effective_shadow_evidence and not bool(evidence.get("effective_shadow_confirmed")):
        reasons.append("INSUFFICIENT_EFFECTIVE_SAMPLE")

    research_skill = float(evidence.get("research_brier_skill", 0.0))
    shadow_skill = float(evidence.get("shadow_brier_skill", 0.0))
    calibration_error = evidence.get("calibration_error")
    if research_skill <= gate.min_research_brier_skill:
        reasons.append("NO_MODEL_BEATS_BASELINE")
    if shadow_skill <= gate.min_shadow_brier_skill:
        reasons.append("NO_MODEL_BEATS_BASELINE")
    if calibration_error is not None and float(calibration_error) > gate.max_calibration_error:
        reasons.append("CALIBRATION_FAILED")

    return GateDecision(
        not reasons,
        "PROMOTION_ELIGIBLE" if not reasons else "UNAVAILABLE",
        sorted(set(reasons)),
        gate.version,
        gate.config_hash,
    )


def reliability(evidence: Mapping[str, Any], gate: GateConfig | None = None) -> str:
    gate = gate or GateConfig()
    if evidence.get("data_health") != "NORMAL":
        return "UNAVAILABLE"
    shadow = float(evidence.get("shadow_brier_skill", 0))
    research = float(evidence.get("research_brier_skill", 0))
    cal = float(evidence.get("calibration_error", 1))
    if shadow > 0.05 and research > 0.05 and cal < min(0.05, gate.max_calibration_error):
        return "HIGH"
    if shadow > 0 and research > 0 and cal < gate.max_calibration_error:
        return "MEDIUM"
    if shadow > 0 and research > 0:
        return "LOW"
    return "UNAVAILABLE"


def demotion_decision(
    *,
    rolling_brier: float,
    baseline_brier: float,
    calibration_error: float | None,
    data_health: str,
    artifact_valid: bool = True,
    max_calibration_error: float = 0.15,
) -> dict:
    reasons = []
    if rolling_brier > baseline_brier:
        reasons.append("BASELINE_SUPERIOR")
    if calibration_error is not None and calibration_error > max_calibration_error:
        reasons.append("CALIBRATION_DRIFT")
    if data_health == "CRITICAL":
        reasons.append("DATA_HEALTH_CRITICAL")
    if not artifact_valid:
        reasons.append("MODEL_ARTIFACT_MISSING")
    return {
        "demote": bool(reasons),
        "to_state": "DEGRADED" if reasons else "PRODUCTION",
        "reasons": reasons,
    }


def emergency_override(action: str, *, operator: str, reason: str, horizon: str = "ALL") -> dict:
    if action.upper() == "PROMOTE":
        raise ValueError("manual override cannot promote a model")
    event = record_override(action, operator=operator, reason=reason, horizon=horizon)
    event["non_standard_flow"] = True
    if action.upper() == "DEMOTE" and horizon != "ALL":
        state = current_model_state(horizon)
        if state and state.get("status") == "PRODUCTION":
            transition_model(
                horizon, "DEGRADED", reason=reason, trigger="emergency_override",
                operator_or_system=operator, gate_version=str(state.get("gate_version") or "v1"),
                patch={"demotion_reasons": ["EMERGENCY_OVERRIDE"]},
            )
    return event


def current_production_approval(horizon: str) -> dict | None:
    record = current_model_state(horizon) or load_latest_record(f"forecast_model_state_{horizon}")
    if not record or record.get("status") != "PRODUCTION":
        return None
    allowed, _ = publication_allowed(horizon)
    return record if allowed else None


def record_promotion(
    horizon: str,
    *,
    model_id: str,
    model_version: str,
    artifact_hash: str,
    experiment_id: str,
    evidence: Mapping[str, Any],
    gate: GateConfig | None = None,
) -> dict:
    gate = gate or GateConfig()
    state = current_model_state(horizon)
    if not state or state.get("status") != "SHADOW":
        raise ValueError("production promotion requires current SHADOW state")
    if state.get("model_id") != model_id or state.get("model_version") != model_version or state.get("artifact_hash") != artifact_hash:
        raise ValueError("shadow state/model artifact mismatch")
    artifact = load_model_artifact(artifact_hash)
    if not artifact or artifact.get("model_id") != model_id or artifact.get("model_version") != model_version:
        raise ValueError("model artifact missing or mismatched")
    experiment = load_experiment(experiment_id)
    if not experiment:
        raise ValueError("experiment registry record missing")
    validate_experiment(experiment, for_promotion=True)
    if experiment.get("model_artifact_hash") != artifact_hash:
        raise ValueError("experiment/model artifact mismatch")
    register_gate_version(gate.version, asdict(gate))
    allowed, reason = publication_allowed(horizon)
    if not allowed:
        raise ValueError(reason or "publication blocked")
    decision = promotion_gate(evidence, gate=gate)
    if not decision.eligible:
        raise ValueError("promotion gate failed: " + ",".join(decision.reasons))
    record = {
        **dict(state),
        "horizon": horizon,
        "status": "PRODUCTION",
        "model_id": model_id,
        "model_version": model_version,
        "artifact_hash": artifact_hash,
        "inference_contract_hash": artifact.get("inference_contract_hash"),
        "experiment_id": experiment_id,
        "dataset_hash": artifact.get("dataset_hash"),
        "config_hash": artifact.get("config_hash"),
        "gate_version": decision.gate_version,
        "gate_hash": decision.gate_hash,
        "evidence_hash": stable_hash(dict(evidence)),
        "evidence": dict(evidence),
    }
    promoted = transition_model(
        horizon, "PRODUCTION", reason="promotion gate + human review", trigger="manual_review",
        operator_or_system="reviewer", gate_version=decision.gate_version, patch=record,
    )
    persist_json_record(f"forecast_model_state_{horizon}", promoted)
    promoted["externally_persisted"] = bool(os.getenv("DATABASE_URL"))
    return promoted


def record_demotion(horizon: str, *, approval: Mapping[str, Any], reasons: list[str]) -> dict:
    state = current_model_state(horizon)
    if state and state.get("status") == "PRODUCTION":
        record = transition_model(
            horizon, "DEGRADED", reason=",".join(reasons) or "automatic demotion",
            trigger="automatic_demotion", operator_or_system="system",
            gate_version=str(state.get("gate_version") or "v1"), patch={"demotion_reasons": list(reasons)},
        )
    else:
        record = dict(approval)
        record["status"] = "DEGRADED"
        record["demotion_reasons"] = list(reasons)
        persist_model_state(record)
    persist_json_record(f"forecast_model_state_{horizon}", record)
    record["externally_persisted"] = bool(os.getenv("DATABASE_URL"))
    return record


def publication_gate(forecast: Mapping[str, Any], approval: Mapping[str, Any] | None, *, horizon: str | None = None) -> dict:
    out = dict(forecast)
    if horizon:
        allowed, control_reason = publication_allowed(horizon)
        if not allowed:
            out.update({"probability_up": None, "state": "UNAVAILABLE", "status": "UNAVAILABLE", "reliability": "UNAVAILABLE", "reason": control_reason})
            return out
    if not approval or approval.get("status") != "PRODUCTION":
        out.update(
            {
                "probability_up": None,
                "state": "UNAVAILABLE",
                "status": "UNAVAILABLE",
                "reliability": "UNAVAILABLE",
                "reason": "NO_PRODUCTION_APPROVAL",
            }
        )
        return out

    expected_version = approval.get("model_version")
    expected_artifact = approval.get("artifact_hash")
    current_version = out.get("model_version")
    current_artifact = out.get("artifact_hash")
    if expected_version and current_version != expected_version:
        out.update(
            {
                "probability_up": None,
                "state": "UNAVAILABLE",
                "status": "UNAVAILABLE",
                "reliability": "UNAVAILABLE",
                "reason": "MODEL_VERSION_MISMATCH",
            }
        )
        return out
    if expected_artifact and current_artifact != expected_artifact:
        out.update(
            {
                "probability_up": None,
                "state": "UNAVAILABLE",
                "status": "UNAVAILABLE",
                "reliability": "UNAVAILABLE",
                "reason": "MODEL_ARTIFACT_MISMATCH",
            }
        )
        return out

    expected_contract = approval.get("inference_contract_hash")
    current_contract = out.get("inference_contract_hash")
    if expected_contract and current_contract != expected_contract:
        out.update({"probability_up": None, "state": "UNAVAILABLE", "status": "UNAVAILABLE", "reliability": "UNAVAILABLE", "reason": "TRAIN_SERVE_SKEW"})
        return out

    out["production_approval"] = {
        "model_id": approval.get("model_id"),
        "model_version": approval.get("model_version"),
        "artifact_hash": approval.get("artifact_hash"),
        "gate_version": approval.get("gate_version"),
        "gate_hash": approval.get("gate_hash"),
    }
    return out
