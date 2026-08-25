from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from eth_trend_v3.calibration_research_v2 import calibration_stability_report
from eth_trend_v3.dynamic_baseline import evaluate_baselines
from eth_trend_v3.feature_ablation_research import run_group_ablation
from eth_trend_v3.horizon_features import build_horizon_features, external_feature_contracts
from eth_trend_v3.model_lifecycle import transition
from eth_trend_v3.probabilistic_research import evaluate_logistic
from eth_trend_v3.promotion import GateConfig, publication_gate, promotion_gate
from eth_trend_v3.regime_conditioning import evaluate_regime_conditioning
from eth_trend_v3.research_validation import purged_walk_forward
from eth_trend_v3.shadow_forecast import settle_shadow_record, shadow_evidence

UTC = timezone.utc


def fixture_rows(n=260):
    out = []
    for i in range(n):
        t = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=4 * i)
        trend = np.sin(i / 8)
        out.append(
            {
                "feature_time": t.isoformat(),
                "timestamp": t.isoformat(),
                "available_at": t.isoformat(),
                "label_start_time": t.isoformat(),
                "label_end_time": (t + timedelta(hours=12)).isoformat(),
                "horizon": "3d",
                "target_up": int(trend > 0),
                "trend": trend,
                "volatility_risk": abs(np.cos(i / 11)),
                "regime": "bull" if i % 80 < 40 else "bear",
                "p_state0": 0.8 if i % 80 < 40 else 0.2,
            }
        )
    return out


def main():
    rows = fixture_rows()
    folds = purged_walk_forward(rows, min_train=120, test_size=30, embargo_hours=4)
    evidence = {}

    evidence["M1"] = {
        "name": "Forecast Research Foundation",
        "software_status": "PASS" if folds and transition("CANDIDATE", "SHADOW", reason="fixture").to_state == "SHADOW" else "FAIL",
        "evidence": {"folds": len(folds), "purge_reports": [f["report"] for f in folds[:2]]},
    }

    baselines = evaluate_baselines(folds, horizon_bars=3, bootstrap_reps=30)
    evidence["M2"] = {
        "name": "Dynamic Baseline Benchmark",
        "software_status": "PASS" if baselines.get("available") else "FAIL",
        "evidence": {"winner": baselines.get("winner"), "candidate_count": len(baselines.get("metrics", {}))},
    }

    ts = pd.date_range("2025-01-01", periods=220, freq="4h", tz="UTC")
    candles = pd.DataFrame({"timestamp": ts, "close": 100 * np.exp(np.cumsum(np.full(220, 0.001))), "volume": np.arange(220) + 100})
    features = build_horizon_features(candles, "3d")
    evidence["M3"] = {
        "name": "Horizon-Aligned Feature Benchmark",
        "software_status": "PASS" if "return_3d" in features.columns and external_feature_contracts() else "FAIL",
        "evidence": {"feature_columns": len(features.columns), "external_contracts": len(external_feature_contracts())},
    }

    simple = evaluate_logistic(folds, ["trend", "volatility_risk"], horizon_bars=3, bootstrap_reps=30)
    evidence["M4"] = {
        "name": "Simple Probabilistic Model Benchmark",
        "software_status": "PASS" if simple.get("available") else "FAIL",
        "evidence": {"passes_incremental_gate_fixture": bool(simple.get("passes_incremental_gate"))},
    }

    ablation = run_group_ablation(
        folds,
        {"trend": ["trend"], "risk": ["volatility_risk"]},
        horizon_bars=3,
        bootstrap_reps=20,
    )
    evidence["M5"] = {
        "name": "Feature Ablation Ladder",
        "software_status": "PASS" if ablation.get("order_robustness") and ablation.get("leave_one_group_out") else "FAIL",
        "evidence": {"survivors": ablation.get("survivor_groups"), "rejected": ablation.get("rejected_groups")},
    }

    regime = evaluate_regime_conditioning(
        folds,
        ["trend"],
        posterior_features=["p_state0"],
        horizon_bars=3,
        bootstrap_reps=20,
    )
    evidence["M6"] = {
        "name": "HMM Regime Conditioning",
        "software_status": "PASS" if regime.get("forecast_role") in {"PREDICTIVE_CANDIDATE", "DESCRIPTIVE_ONLY"} else "FAIL",
        "evidence": {"forecast_role_fixture": regime.get("forecast_role"), "passing": regime.get("passing")},
    }

    raw_fit = np.linspace(0.1, 0.9, 120)
    y_fit = (raw_fit > 0.5).astype(int)
    raw_val = np.linspace(0.15, 0.85, 40)
    y_val = (raw_val > 0.5).astype(int)
    raw_test = np.linspace(0.2, 0.8, 40)
    y_test = (raw_test > 0.5).astype(int)
    cal = calibration_stability_report(raw_fit, y_fit, raw_val, y_val, raw_test, y_test, eligible=True)
    evidence["M7"] = {
        "name": "Calibration Research",
        "software_status": "PASS" if cal.get("available") and cal.get("selection_used_test") is False else "FAIL",
        "evidence": {"selected_fixture": cal.get("selected"), "selection_used_test": cal.get("selection_used_test")},
    }

    shadows = []
    for i in range(50):
        rec = {
            "forecast_id": f"fixture-{i}",
            "mode": "SHADOW",
            "horizon": "3d",
            "probability": 0.6,
            "baseline_probability": 0.5,
            "data_health": "NORMAL",
            "regime": "bull" if i < 25 else "bear",
            "settled": False,
        }
        shadows.append(settle_shadow_record(rec, entry_price=100, path_prices=[98, 101]))
    shadow = shadow_evidence(shadows, horizon="3d", effective_evidence_confirmed=False)
    evidence["M8"] = {
        "name": "Shadow Forecast",
        "software_status": "PASS" if shadow.get("raw_count_gate") and not shadow.get("promotion_evidence_ready") else "FAIL",
        "evidence": {
            "settled_fixture": shadow.get("settled_n"),
            "effective_evidence_confirmed": shadow.get("effective_evidence_confirmed"),
            "promotion_evidence_ready": shadow.get("promotion_evidence_ready"),
        },
    }

    gate_evidence = {
        "leakage_free": True,
        "pit_valid": True,
        "registry_complete": True,
        "artifact_valid": True,
        "train_serve_parity": True,
        "shadow_complete": True,
        "data_health_normal": True,
        "emergency_freeze_clear": True,
        "effective_shadow_confirmed": False,
        "research_brier_skill": 0.03,
        "shadow_brier_skill": 0.02,
        "calibration_error": 0.05,
    }
    decision = promotion_gate(gate_evidence, gate=GateConfig(version="evidence-v1"))
    closed = publication_gate({"probability_up": 0.6, "status": "CALIBRATED"}, None)
    evidence["M9"] = {
        "name": "Production Promotion",
        "software_status": "PASS" if not decision.eligible and closed.get("probability_up") is None else "FAIL",
        "evidence": {"fail_closed_reasons": decision.reasons, "publication_reason": closed.get("reason")},
    }

    all_pass = all(m["software_status"] == "PASS" for m in evidence.values())
    report = {
        "implementation_plan": "forecast-research-implementation-plan-v1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "software_implementation_status": "PASS" if all_pass else "FAIL",
        "milestones": evidence,
        "statistical_production_status": "NOT_GRANTED",
        "statistical_note": (
            "This report validates implementation capabilities with deterministic fixtures. It does not establish live ETH predictive value. "
            "Production promotion requires real OOS + shadow evidence and remains fail-closed."
        ),
    }
    target = Path("eth_reports/forecast-research/implementation_evidence.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    if not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
