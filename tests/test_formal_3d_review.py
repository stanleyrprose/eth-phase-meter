from __future__ import annotations

from datetime import datetime, timedelta, timezone

from eth_trend_v3.formal_3d_review import (
    HORIZON_BARS,
    _fold_summary,
    _prepare_rows,
)
from eth_trend_v3.research_validation import purged_walk_forward


def _records(n: int = 170) -> list[dict]:
    start = datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        ts = start + timedelta(hours=4 * i)
        price = 100 + i * 0.2 + (2 if i % 5 == 0 else 0)
        out.append(
            {
                "observed_at": ts.isoformat(),
                "schedule_nominal_time": ts.isoformat(),
                "github_event": "schedule",
                "metric_value": {"timeframe": "4h", "price": price},
                "coverage": 98,
                "regime": {"regime": "Low-Vol Bull" if i % 2 else "Transition"},
                "market_state_vector": {
                    "dimensions": {
                        "trend": {"score": float((i % 7) - 3)},
                        "crowding": {"score": float((i % 5) - 2)},
                        "volatility_risk": {"score": float((i % 3) - 1)},
                        "valuation": {"score": 0.0},
                        "capital_flow": {"score": 0.0},
                        "structural_supply": {"score": 0.0},
                    }
                },
                "raw_payload": {},
            }
        )
    return out


def test_formal_rows_include_required_time_contract():
    rows = _prepare_rows(_records())
    row = rows[0]
    for key in ("feature_time", "available_at", "label_start_time", "label_end_time", "horizon"):
        assert row.get(key)
    assert row["horizon"] == "3d"


def test_purged_folds_remove_overlapping_3d_training_labels():
    rows = _prepare_rows(_records())
    folds = purged_walk_forward(rows, min_train=120, test_size=24, embargo_hours=4)
    assert folds
    for fold in folds:
        test_start = datetime.fromisoformat(fold["report"]["test_start"])
        for train in fold["train"]:
            label_end = datetime.fromisoformat(train["label_end_time"])
            assert label_end < test_start
        assert fold["report"]["purged_count"] > 0


def test_effective_sample_uses_3d_18_bar_horizon():
    rows = _prepare_rows(_records())
    folds = purged_walk_forward(rows, min_train=120, test_size=24, embargo_hours=4)
    summary = _fold_summary(folds)
    assert summary["effective_sample_diagnostic"]["horizon_bars"] == HORIZON_BARS == 18
    assert summary["leakage_guard_passed"] is True
