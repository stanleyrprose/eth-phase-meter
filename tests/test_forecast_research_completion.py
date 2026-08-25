from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from eth_trend_v3.calibration_research_v2 import calibration_stability_report
from eth_trend_v3.dynamic_baseline import BaselineSpec, evaluate_baselines, predict_baseline
from eth_trend_v3.feature_ablation_research import run_group_ablation
from eth_trend_v3.horizon_features import FeatureMeta, build_horizon_features, external_feature_contracts, validate_feature_contract
from eth_trend_v3.promotion import GateConfig, emergency_override, publication_gate, promotion_gate
from eth_trend_v3.regime_conditioning import evaluate_regime_conditioning
from eth_trend_v3.research_validation import purged_walk_forward
from eth_trend_v3.shadow_forecast import settle_shadow_record, shadow_evidence

UTC = timezone.utc


def _rows(n=260, label_h=12):
    rows = []
    for i in range(n):
        t = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=4 * i)
        trend = np.sin(i / 8)
        rows.append(
            {
                "feature_time": t.isoformat(),
                "timestamp": t.isoformat(),
                "available_at": t.isoformat(),
                "label_start_time": t.isoformat(),
                "label_end_time": (t + timedelta(hours=label_h)).isoformat(),
                "horizon": "3d",
                "target_up": int(trend > 0),
                "trend": trend,
                "volatility_risk": abs(np.cos(i / 11)),
                "regime": "bull" if i % 80 < 40 else "bear",
                "p_state0": 0.8 if i % 80 < 40 else 0.2,
            }
        )
    return rows


def test_regime_baselines_and_conservative_champion_selection():
    rows = _rows()
    folds = purged_walk_forward(rows, min_train=120, test_size=30)
    report = evaluate_baselines(folds, horizon_bars=3, bootstrap_reps=50)
    assert report["available"]
    assert "hard-regime-min20" in report["metrics"]
    assert "shrunk-regime-prior20" in report["metrics"]
    p = predict_baseline(rows[:120], rows[120:125], BaselineSpec("shrunk_regime"))
    assert len(p) == 5 and np.all((p > 0) & (p < 1))


def test_feature_contract_rejects_silent_zero_and_macro_requires_availability():
    bad = FeatureMeta("x", "v1", "s", "x", "1", "closed", "0", "zero", "c", "3d")
    with pytest.raises(ValueError):
        validate_feature_contract(bad)
    assert external_feature_contracts()
    ts = pd.date_range("2025-01-01", periods=20, freq="4h", tz="UTC")
    candles = pd.DataFrame({"timestamp": ts, "close": np.arange(20) + 100, "volume": np.arange(20) + 10})
    with pytest.raises(ValueError):
        build_horizon_features(candles, "3d", pd.DataFrame({"dxy_return": [0.1]}))


def test_ablation_reports_order_robustness():
    rows = _rows()
    folds = purged_walk_forward(rows, min_train=120, test_size=30)
    report = run_group_ablation(
        folds,
        {"trend": ["trend"], "risk": ["volatility_risk"]},
        horizon_bars=3,
        bootstrap_reps=30,
    )
    assert report["order_robustness"]
    assert set(report["survivor_groups"] + report["rejected_groups"]) == {"trend", "risk"}


def test_regime_conditioning_returns_explicit_role():
    rows = _rows()
    folds = purged_walk_forward(rows, min_train=120, test_size=30)
    report = evaluate_regime_conditioning(
        folds,
        ["trend"],
        posterior_features=["p_state0"],
        horizon_bars=3,
        bootstrap_reps=30,
    )
    assert report["forecast_role"] in {"PREDICTIVE_CANDIDATE", "DESCRIPTIVE_ONLY"}


def test_calibration_stability_selects_without_using_test():
    fit = np.linspace(0.1, 0.9, 120)
    y_fit = (fit > 0.5).astype(int)
    val = np.linspace(0.15, 0.85, 40)
    y_val = (val > 0.5).astype(int)
    test = np.linspace(0.2, 0.8, 40)
    y_test = (test > 0.5).astype(int)
    report = calibration_stability_report(fit, y_fit, val, y_val, test, y_test, eligible=True)
    assert report["available"] and report["selection_used_test"] is False


def test_shadow_settlement_and_evidence_remain_fail_closed_without_effective_confirmation():
    records = []
    for i in range(50):
        record = {
            "forecast_id": f"f{i}",
            "mode": "SHADOW",
            "horizon": "3d",
            "probability": 0.6,
            "baseline_probability": 0.5,
            "data_health": "NORMAL",
            "regime": "bull" if i < 25 else "bear",
            "settled": False,
        }
        records.append(settle_shadow_record(record, entry_price=100, path_prices=[98, 101]))
    evidence = shadow_evidence(records, horizon="3d", effective_evidence_confirmed=False)
    assert evidence["raw_count_gate"] is True
    assert evidence["regime_gate"] is True
    assert evidence["promotion_evidence_ready"] is False
    evidence2 = shadow_evidence(records, horizon="3d", effective_evidence_confirmed=True)
    assert evidence2["promotion_evidence_ready"] is True


def test_versioned_promotion_gate_and_publication_fail_closed():
    evidence = {
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
    gate = GateConfig(version="gate-v2")
    decision = promotion_gate(evidence, gate=gate)
    assert not decision.eligible and "INSUFFICIENT_EFFECTIVE_SAMPLE" in decision.reasons
    closed = publication_gate({"probability_up": 0.62, "status": "CALIBRATED"}, None)
    assert closed["probability_up"] is None and closed["reason"] == "NO_PRODUCTION_APPROVAL"
    with pytest.raises(ValueError):
        emergency_override("PROMOTE", operator="admin", reason="not allowed")
