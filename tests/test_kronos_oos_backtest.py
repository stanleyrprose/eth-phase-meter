import pandas as pd

from scripts.run_kronos_oos_backtest import (
    OOS_START,
    _binomial_p_two_sided,
    _direction_hit,
    _select_points,
    _subperiod_metrics,
)


def test_select_points_are_oos_and_non_overlapping():
    timestamps = pd.date_range("2024-06-01", periods=400, freq="4h", tz="UTC")
    df = pd.DataFrame({"timestamps": timestamps})
    points = _select_points(
        df,
        lookback=90,
        pred_len=18,
        stride_bars=18,
        max_points=10,
    )
    assert points
    assert all(df.iloc[index]["timestamps"] >= OOS_START for index in points)
    assert all(b - a >= 18 for a, b in zip(points, points[1:]))


def test_direction_hit_and_binomial_are_diagnostic():
    assert _direction_hit(1.0, 2.0) is True
    assert _direction_hit(-1.0, 2.0) is False
    assert _direction_hit(0.0, 2.0) is None
    assert _binomial_p_two_sided(3, 3) == 0.25


def test_subperiod_metrics_split_calendar_periods():
    rows = []
    for timestamp in ("2024-08-01T00:00:00Z", "2025-06-01T00:00:00Z", "2026-06-01T00:00:00Z"):
        rows.append(
            {
                "source_timestamp": timestamp,
                "kronos_direction_hit": True,
                "momentum_direction_hit": False,
                "kronos_return_pct": 1.0,
                "actual_return_pct": 2.0,
                "kronos_abs_price_error_pct": 1.0,
                "persistence_abs_price_error_pct": 2.0,
                "momentum_abs_price_error_pct": 3.0,
            }
        )
    result = _subperiod_metrics(rows)
    assert result["2024H2"]["n"] == 1
    assert result["2025"]["n"] == 1
    assert result["2026YTD"]["n"] == 1
