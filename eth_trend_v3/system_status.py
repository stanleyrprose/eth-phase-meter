from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .dataset import HORIZONS, load_pit_records, pit_history_depth
from .experiment_registry import load_experiment
from .governance import holdout_record
from .model_artifact import load_model_artifact
from .model_state import current_model_state
from .persistence import load_latest_record
from .shadow_forecast import load_shadow_records, shadow_evidence


def build_system_status() -> dict:
    monitor = load_latest_record("monitor_state_4h") or {}
    forecasts = monitor.get("forecasts") or {}
    shadows = load_shadow_records()
    pit_depth = pit_history_depth(load_pit_records())
    horizons = {}
    production_active = False
    for horizon in HORIZONS:
        state = current_model_state(horizon)
        forecast = forecasts.get(horizon) or {}
        artifact = load_model_artifact(str((state or {}).get("artifact_hash") or "")) if state else None
        experiment = load_experiment(str((state or {}).get("experiment_id") or "")) if state else None
        family = (experiment or {}).get("experiment_family")
        holdout = holdout_record(str(family)) if family else None
        evidence = shadow_evidence(shadows, horizon=horizon, effective_evidence_confirmed=False)
        production_active = production_active or bool(state and state.get("status") == "PRODUCTION")
        state_evidence = (state or {}).get("evidence") or {}
        horizons[horizon] = {
            "lifecycle_status": (state or {}).get("status") or "UNAVAILABLE",
            "dynamic_baseline": (artifact or {}).get("baseline_spec"),
            "production_model": {
                "model_id": (state or {}).get("model_id"),
                "model_version": (state or {}).get("model_version"),
                "artifact_hash": (state or {}).get("artifact_hash"),
                "inference_contract_hash": (state or {}).get("inference_contract_hash"),
            } if state and state.get("status") == "PRODUCTION" else None,
            "published_probability": forecast.get("probability_up"),
            "unavailable_reason": forecast.get("reason") if forecast.get("probability_up") is None else None,
            "research_metrics": {
                "brier": state_evidence.get("brier"),
                "brier_skill_score": state_evidence.get("research_brier_skill") or state_evidence.get("brier_skill_score"),
                "log_loss": state_evidence.get("log_loss"),
                "calibration_error": state_evidence.get("calibration_error"),
            },
            "shadow": evidence,
            "data_health": (monitor.get("data_health") or {}).get("status"),
            "last_transition": (state or {}).get("last_transition"),
            "git_sha": (artifact or {}).get("git_sha") or (experiment or {}).get("git_sha"),
            "experiment_id": (state or {}).get("experiment_id"),
            "dataset_hash": (artifact or {}).get("dataset_hash") or (experiment or {}).get("dataset_hash"),
            "config_hash": (artifact or {}).get("config_hash") or (experiment or {}).get("config_hash"),
            "artifact_hash": (state or {}).get("artifact_hash"),
            "gate_version": (state or {}).get("gate_version") or (experiment or {}).get("gate_version"),
            "holdout_status": (holdout or {}).get("status") or (experiment or {}).get("holdout_status") or "UNREGISTERED",
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engineering_scope": "Forecast Research Phase 1-9 / PRD v2.3",
        "statistical_production_status": "GRANTED_FOR_ACTIVE_APPROVALS" if production_active else "NOT_GRANTED",
        "data_health": monitor.get("data_health") or {},
        "pit_history_depth": pit_depth,
        "horizons": horizons,
    }


def write_system_status(path: str = "eth_reports/forecast-research/system_status.json") -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_system_status(), indent=2, default=str), encoding="utf-8")
    return str(target)
