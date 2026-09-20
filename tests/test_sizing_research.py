from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from eth_trend_v3.sizing_research import (
    SizingResearchConfig,
    build_sizing_intervals,
    run_sizing_research,
)


def pit(
    index: int,
    *,
    direction: int = 40,
    coverage: float = 90.0,
    event: str = "schedule",
    price: float | None = None,
) -> dict:
    nominal = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=4 * index)
    observed = nominal + timedelta(minutes=7)
    px = float(price if price is not None else 100.0 + index)
    return {
        "event_time": observed.strftime("%Y-%m-%d %H:%M UTC"),
        "observed_at": observed.isoformat(),
        "schedule_nominal_time": nominal.isoformat(),
        "metric_value": {
            "timeframe": "4h",
            "price": px,
            "final_direction": direction,
            "rule_regime": "TREND_UP",
        },
        "coverage": coverage,
        "regime": {"regime": "TREND_UP" if direction >= 0 else "RANGE"},
        "github_event": event,
        "workflow_run_id": str(index),
        "raw_payload_hash": f"hash-{index}-{event}",
    }


def test_manual_retry_does_not_create_extra_interval():
    records = [pit(i) for i in range(8)]
    retry = pit(3, direction=-90, event="workflow_dispatch", price=999.0)
    records.append(retry)
    frame = build_sizing_intervals(
        records,
        SizingResearchConfig(vol_window=3, vol_min_periods=2),
    )
    assert len(frame) == 7
    row = frame[frame["nominal_time"] == frame["nominal_time"].min() + timedelta(hours=12)].iloc[0]
    assert row["price"] != 999.0
    assert row["direction"] != -90


def test_missing_scheduled_bucket_is_not_treated_as_one_4h_interval():
    records = [pit(0), pit(1), pit(3), pit(4)]
    frame = build_sizing_intervals(
        records,
        SizingResearchConfig(vol_window=2, vol_min_periods=1),
    )
    assert len(frame) == 2
    assert all(frame["nominal_gap_hours"] <= 4.5)


def test_trailing_volatility_uses_only_prior_returns():
    records = [
        pit(0, price=100),
        pit(1, price=101),
        pit(2, price=102),
        pit(3, price=130),
        pit(4, price=131),
    ]
    frame = build_sizing_intervals(
        records,
        SizingResearchConfig(vol_window=2, vol_min_periods=2),
    )
    first_with_vol = frame[frame["trailing_ann_vol"].notna()].iloc[0]
    prior = frame.iloc[:2]["asset_return"]
    expected = prior.std(ddof=1) * (6.0 * 365.25) ** 0.5
    assert first_with_vol["trailing_ann_vol"] == pytest.approx(expected)


def test_small_sample_never_auto_promotes_sizing():
    records = [
        pit(i, direction=60 if i % 3 else -20, price=100 + i * 0.5)
        for i in range(40)
    ]
    report = run_sizing_research(
        records,
        SizingResearchConfig(
            review_checkpoint_intervals=25,
            vol_window=4,
            vol_min_periods=2,
            bootstrap_samples=50,
            bootstrap_block=2,
        ),
    )
    assert report["review_checkpoint_reached"] is True
    assert report["status"] == "READY_FOR_HUMAN_SIZING_REVIEW"
    assert report["automatic_sizing_promotion_allowed"] is False
    assert report["automatic_shadow_allowed"] is False
    assert report["automatic_production_allowed"] is False
    assert report["paper_execution_allowed"] is False
    assert report["live_execution_allowed"] is False


def test_default_checkpoint_waits_below_250_intervals():
    records = [pit(i, direction=30, price=100 + i) for i in range(80)]
    report = run_sizing_research(
        records,
        SizingResearchConfig(
            vol_window=4,
            vol_min_periods=2,
            bootstrap_samples=50,
            bootstrap_block=2,
        ),
    )
    assert report["raw_valid_intervals"] == 79
    assert report["review_checkpoint_target_intervals"] == 250
    assert report["review_checkpoint_reached"] is False
    assert report["status"] == "WAIT_FOR_MORE_PIT_SIZING_EVIDENCE"
