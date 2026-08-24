import numpy as np
import pandas as pd

from eth_trend_v3.baseline_benchmark import _metrics, run_benchmark


def test_metrics_prefers_perfect_predictions():
    y = np.array([0, 1, 0, 1])
    good = _metrics(y, [0.01, 0.99, 0.01, 0.99])
    bad = _metrics(y, [0.5, 0.5, 0.5, 0.5])
    assert good["brier"] < bad["brier"]
    assert good["log_loss"] < bad["log_loss"]


def test_benchmark_report_never_allows_production_change():
    rng = np.random.default_rng(7)
    n = 700
    r = rng.normal(0, 0.01, n)
    df = pd.DataFrame({
        "log_return": r,
        "log_return_24h": pd.Series(r).rolling(6).sum().fillna(0),
        "realized_volatility": pd.Series(r).rolling(12).std().fillna(0.01),
        "log_volume_change": rng.normal(0, 0.2, n),
    })
    report = run_benchmark(df, min_train=450, test_size=60)
    assert report["production_change_allowed"] is False
    assert set(report["horizons"]) == {"3d", "7d", "30d"}
