import unittest

import numpy as np
import pandas as pd

from eth_trend_v3.hmm_bootstrap import (
    apply_robust_scaler,
    build_bootstrap_features,
    fit_robust_scaler,
    hmm_parameter_count,
    label_state_profile,
    normalized_entropy,
    seed_stability,
)


class HMMBootstrapTests(unittest.TestCase):
    def test_build_features_has_no_fake_oi(self):
        n = 40
        bars = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
            "close": np.linspace(2000, 2200, n),
            "volume": np.linspace(1000, 1500, n),
        })
        out = build_bootstrap_features(bars)
        self.assertGreater(len(out), 20)
        self.assertEqual(list(out.columns), ["timestamp", "log_return", "realized_volatility", "log_volume_change"])
        self.assertNotIn("oi_change", out.columns)

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

    def test_entropy_is_low_for_confident_and_high_for_uniform(self):
        self.assertLess(normalized_entropy([0.97, 0.01, 0.01, 0.01]), 0.2)
        self.assertAlmostEqual(normalized_entropy([0.25, 0.25, 0.25, 0.25]), 1.0, places=6)

    def test_state_label_uses_profile_not_state_id(self):
        bull = label_state_profile({"log_return": 0.003, "realized_volatility": 0.01}, vol_median=0.02)
        bear = label_state_profile({"log_return": -0.004, "realized_volatility": 0.04}, vol_median=0.02)
        self.assertEqual(bull, "Low-Vol Bull")
        self.assertEqual(bear, "High-Vol Bear")


if __name__ == "__main__":
    unittest.main()
