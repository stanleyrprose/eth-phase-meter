from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .experiment_registry import stable_hash
from .persistence import load_latest_record, persist_json_record

UNAVAILABLE_REASONS = {
    "NO_MODEL_BEATS_BASELINE",
    "INSUFFICIENT_DATA",
    "INSUFFICIENT_EFFECTIVE_SAMPLE",
    "CALIBRATION_FAILED",
    "DATA_HEALTH_CRITICAL",
    "MODEL_DEGRADED",
    "MODEL_ARTIFACT_MISSING",
    "FEATURE_UNAVAILABLE",
    "SOURCE_CONTRACT_FAILED",
    "SHADOW_INSUFFICIENT",
    "REGISTRY_INCOMPLETE",
    "LEAKAGE_DETECTED",
    "TRAIN_SERVE_SKEW",
    "HOLDOUT_CONTAMINATED",
    "NO_PRODUCTION_APPROVAL",
    "MODEL_VERSION_MISMATCH",
    "MODEL_ARTIFACT_MISMATCH",
}


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
        "emergency_freeze_clear": "DATA_HEALTH_CRITICAL",
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


def emergency_override(action: str, *, operator: str, reason: str) -> dict:
    allowed = {"FREEZE", "DEMOTE", "DISABLE_PUBLICATION", "ANNOTATE"}
    if action not in allowed:
        raise ValueError("manual override cannot promote a model")
    if not operator or not reason:
        raise ValueError("operator and reason required")
    from datetime import datetime, timezone

    return {
        "action": action,
        "operator": operator,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "non_standard_flow": True,
    }


def current_production_approval(horizon: str) -> dict | None:
    record = load_latest_record(f"forecast_model_state_{horizon}")
    if not record or record.get("status") != "PRODUCTION":
        return None
    return record


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
    decision = promotion_gate(evidence, gate=gate)
    if not decision.eligible:
        raise ValueError("promotion gate failed: " + ",".join(decision.reasons))
    record = {
        "horizon": horizon,
        "status": "PRODUCTION",
        "model_id": model_id,
        "model_version": model_version,
        "artifact_hash": artifact_hash,
        "experiment_id": experiment_id,
        "gate_version": decision.gate_version,
        "gate_hash": decision.gate_hash,
        "evidence_hash": stable_hash(dict(evidence)),
        "evidence": dict(evidence),
    }
    persisted = persist_json_record(f"forecast_model_state_{horizon}", record)
    record["externally_persisted"] = bool(persisted)
    return record


def record_demotion(horizon: str, *, approval: Mapping[str, Any], reasons: list[str]) -> dict:
    record = dict(approval)
    record["status"] = "DEGRADED"
    record["demotion_reasons"] = list(reasons)
    record["externally_persisted"] = bool(persist_json_record(f"forecast_model_state_{horizon}", record))
    return record


def publication_gate(forecast: Mapping[str, Any], approval: Mapping[str, Any] | None) -> dict:
    out = dict(forecast)
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

    out["production_approval"] = {
        "model_id": approval.get("model_id"),
        "model_version": approval.get("model_version"),
        "artifact_hash": approval.get("artifact_hash"),
        "gate_version": approval.get("gate_version"),
        "gate_hash": approval.get("gate_hash"),
    }
    return out
