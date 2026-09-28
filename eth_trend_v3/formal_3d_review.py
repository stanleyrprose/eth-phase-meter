from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .dataset import build_labeled_rows, canonicalize_pit_records
from .dynamic_baseline import BaselineSpec, default_specs, evaluate_baselines
from .probabilistic_research import evaluate_logistic
from .regime_conditioning import evaluate_regime_conditioning
from .research_metrics import effective_sample_diagnostic
from .research_validation import purged_walk_forward

HORIZON = "3d"
HORIZON_HOURS = 72
BAR_HOURS = 4
HORIZON_BARS = 18
MIN_TRAIN = 120
TEST_SIZE = 24
EMBARGO_HOURS = 4.0
BOOTSTRAP_REPS = 2000

CANDIDATE_SPECS: dict[str, list[str]] = {
    "trend": ["trend"],
    "core": ["trend", "crowding", "volatility_risk"],
    "core_plus_regime_code": ["trend", "crowding", "volatility_risk", "regime_code"],
    "core_plus_derivatives": ["trend", "crowding", "volatility_risk", "funding_rate", "open_interest"],
    "core_plus_options": [
        "trend",
        "crowding",
        "volatility_risk",
        "put_call_oi_ratio",
        "atm_iv_near",
        "iv_skew_25d_proxy_near",
        "iv_term_structure_near_next",
    ],
    "core_plus_macro_rates": [
        "trend",
        "crowding",
        "volatility_risk",
        "dxy_return",
        "us10y_change_bps",
        "us2y_change_bps",
        "real10y_change_bps",
        "yield_curve_10y2y_pp",
    ],
    "core_plus_crypto_beta": [
        "trend",
        "crowding",
        "volatility_risk",
        "btc_return_24h_pct",
        "ethbtc_return_24h_pct",
    ],
    "core_plus_capital_flow": ["trend", "crowding", "volatility_risk", "capital_flow"],
    "core_plus_structural": ["trend", "crowding", "volatility_risk", "structural_supply"],
    "core_plus_valuation": ["trend", "crowding", "volatility_risk", "valuation"],
}


def _baseline_spec(key: str) -> BaselineSpec:
    specs = {spec.key: spec for spec in default_specs()}
    if key not in specs:
        raise ValueError(f"unknown baseline key: {key}")
    return specs[key]


def _prepare_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = build_labeled_rows(records, HORIZON_HOURS)
    prepared: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["feature_time"] = item["timestamp"]
        item["available_at"] = item["timestamp"]
        item["label_start_time"] = item["timestamp"]
        item["label_end_time"] = item["future_timestamp"]
        item["horizon"] = HORIZON
        item["regime"] = item.get("regime_code")
        prepared.append(item)
    return prepared


def _fold_summary(folds: list[dict[str, Any]]) -> dict[str, Any]:
    reports = [dict(fold["report"]) for fold in folds]
    oos_n = sum(int(r["test_count"]) for r in reports)
    return {
        "fold_count": len(reports),
        "reports": reports,
        "oos_n": oos_n,
        "effective_sample_diagnostic": effective_sample_diagnostic(oos_n, HORIZON_BARS),
        "min_train_after_purge": min((int(r["train_after"]) for r in reports), default=0),
        "max_purged_ratio": max((float(r["purged_ratio"]) for r in reports), default=0.0),
        "leakage_guard_passed": bool(reports),
    }


def run_formal_3d_review(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = _prepare_rows(records)
    folds = purged_walk_forward(
        rows,
        min_train=MIN_TRAIN,
        test_size=TEST_SIZE,
        embargo_hours=EMBARGO_HOURS,
    )
    fold_summary = _fold_summary(folds)

    baselines = evaluate_baselines(
        folds,
        horizon_bars=HORIZON_BARS,
        bootstrap_reps=BOOTSTRAP_REPS,
    )
    baseline_key = str(baselines.get("winner") or "expanding")
    baseline_spec = _baseline_spec(baseline_key)

    candidates: dict[str, Any] = {}
    passing: list[str] = []
    for name, features in CANDIDATE_SPECS.items():
        result = evaluate_logistic(
            folds,
            features,
            horizon_bars=HORIZON_BARS,
            baseline_spec=baseline_spec,
            bootstrap_reps=BOOTSTRAP_REPS,
        )
        candidates[name] = result
        if result.get("passes_incremental_gate"):
            passing.append(name)

    regime = evaluate_regime_conditioning(
        folds,
        ["trend", "crowding", "volatility_risk"],
        posterior_features=None,
        horizon_bars=HORIZON_BARS,
        regime_key="regime",
        bootstrap_reps=BOOTSTRAP_REPS,
    )

    if not folds:
        status = "INSUFFICIENT_PURGED_OOS"
        next_action = "ACCUMULATE_MORE_PIT"
    elif passing:
        status = "CANDIDATE_INCREMENTAL_EVIDENCE"
        next_action = "FORMAL_CALIBRATION_AND_HOLDOUT_REVIEW"
    else:
        status = "NO_CANDIDATE_BEATS_DYNAMIC_BASELINE"
        next_action = "KEEP_GATED_AND_ACCUMULATE"

    canonical = canonicalize_pit_records(records, timeframe="4h")
    return {
        "contract_version": "eth-3d-formal-research-review-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "horizon": HORIZON,
        "status": status,
        "next_action": next_action,
        "data": {
            "source_records": len(records),
            "canonical_4h_records": len(canonical),
            "labeled_3d_rows": len(rows),
        },
        "methodology": {
            "purged_walk_forward": True,
            "horizon_hours": HORIZON_HOURS,
            "bar_hours": BAR_HOURS,
            "horizon_bars": HORIZON_BARS,
            "min_train_pre_purge": MIN_TRAIN,
            "test_size": TEST_SIZE,
            "embargo_hours": EMBARGO_HOURS,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "moving_block_sensitivity": ["0.5H", "1.0H", "1.5H"],
        },
        "folds": fold_summary,
        "dynamic_baseline": baselines,
        "selected_dynamic_baseline": baseline_key,
        "candidates": candidates,
        "passing_candidates": passing,
        "regime_conditioning": regime,
        "calibration": {
            "status": "DEFERRED_UNTIL_RAW_INCREMENTAL_GATE"
            if not passing
            else "REQUIRES_FORMAL_REVIEW",
            "reason": (
                "Calibration cannot rescue an ineligible raw model."
                if not passing
                else "At least one raw candidate passed the incremental gate."
            ),
        },
        "governance": {
            "production_eligible": False,
            "shadow_activation_allowed": False,
            "production_activation_allowed": False,
            "paper_execution_allowed": False,
            "live_execution_allowed": False,
            "automatic_capital_allocation_allowed": False,
        },
        "limitations": [
            "Adjacent 3D targets overlap heavily; effective sample is diagnostic rather than a precise ESS.",
            "This review is a research gate, not Production Approval.",
            "Untouched holdout and forward Shadow evidence remain separate requirements.",
        ],
    }
