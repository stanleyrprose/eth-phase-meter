import unittest

import numpy as np
import pandas as pd

from eth_trend_v3.hmm_bootstrap import (
    _directional_separation,
    _profile_distance,
    apply_robust_scaler,
    build_bootstrap_features,
    fit_robust_scaler,
    hmm_parameter_count,
    label_state_profile,
    normalized_entropy,
    seed_stability,
)


class HMMBootstrapTests(unittest.TestCase):
    def test_build_features_has_both_return_horizons_and_no_fake_oi(self):
        n = 60
        bars = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
            "close": np.linspace(2000, 2300, n),
            "volume": np.linspace(1000, 1500, n),
        })
        out = build_bootstrap_features(bars)
        self.assertGreater(len(out), 30)
        self.assertEqual(
            list(out.columns),
            ["timestamp", "log_return", "log_return_24h", "realized_volatility", "log_volume_change"],
        )
        self.assertNotIn("oi_change", out.columns)
        self.assertTrue(np.isfinite(out[["log_return", "log_return_24h"]].to_numpy()).all())

    def test_24h_return_is_six_4h_bars(self):
        n = 20
        close = 100.0 * np.exp(np.arange(n) * 0.01)
        bars = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
            "close": close,
            "volume": np.full(n, 1000.0),
        })
        out = build_bootstrap_features(bars)
        self.assertTrue(np.allclose(out["log_return_24h"].to_numpy(), 0.06, atol=1e-10))

    def test_directional_separation_requires_positive_and_negative_states(self):
        profiles = [
            {"log_return_24h": 0.02},
            {"log_return_24h": -0.015},
            {"log_return_24h": 0.001},
        ]
        result = _directional_separation(profiles, "log_return_24h")
        self.assertTrue(result["passes"])
        self.assertEqual(result["bullish_states"], 1)
        self.assertEqual(result["bearish_states"], 1)

        flat = [{"log_return_24h": 0.001}, {"log_return_24h": 0.002}]
        self.assertFalse(_directional_separation(flat, "log_return_24h")["passes"])

    def test_profile_distance_zero_for_identical_profiles(self):
        a = np.array([[0.1, 1.0], [0.2, 2.0], [0.3, 3.0]])
        self.assertAlmostEqual(_profile_distance(a, a.copy()), 0.0)

    def test_robust_scaler_is_trainable_and_clipped(self):
        x = np.array([[0.0, 1.0], [1.0, 2.0], [2.0, 3.0], [1000.0, -1000.0]])
        scaler = fit_robust_scaler(x[:3])
        z = apply_robust_scaler(x, scaler)
        self.assertTrue(np.all(z <= 5.0))
        self.assertTrue(np.all(z >= -5.0))

    def test_parameter_count_positive(self):
        self.assertGreater(hmm_parameter_count(4, 3), 0)

    def test_seed_stability_is_label_invariant(self):
        a = np.array([0, 0, 1, 1, 2, 2])
        b = np.array([2, 2, 0, 0, 1, 1])
        self.assertAlmostEqual(seed_stability([a, b]), 1.0)

    def test_normalized_entropy_distinguishes_certainty(self):
        self.assertAlmostEqual(normalized_entropy([1.0, 0.0, 0.0]), 0.0)
        self.assertAlmostEqual(normalized_entropy([1/3, 1/3, 1/3]), 1.0, places=6)

    def test_state_profile_label_uses_return_and_relative_vol(self):
        self.assertEqual(
            label_state_profile({"log_return": 0.004, "realized_volatility": 0.03}, 0.02),
            "High-Vol Bull",
        )
        self.assertEqual(
            label_state_profile({"log_return": -0.004, "realized_volatility": 0.01}, 0.02),
            "Low-Vol Bear",
        )
        self.assertEqual(
            label_state_profile({"log_return": 0.0002, "realized_volatility": 0.01}, 0.02),
            "Low-Vol Sideways",
        )


if __name__ == "__main__":
    unittest.main()
