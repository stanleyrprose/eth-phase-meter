import pandas as pd

from scripts.run_kronos_oos_backtest import (
    OOS_START,
    _binomial_p_two_sided,
    _direction_hit,
    _select_points,
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
