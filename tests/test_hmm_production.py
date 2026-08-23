import unittest
import numpy as np

from eth_trend_v3.hmm_production import causal_filter, build_production_model_record


class HMMProductionTests(unittest.TestCase):
    def test_causal_filter_is_normalized(self):
        params = {
            "n_states": 2,
            "startprob": [0.5, 0.5],
            "transmat": [[0.9, 0.1], [0.1, 0.9]],
            "means": [[-1.0], [1.0]],
            "covars": [[[0.25]], [[0.25]]],
        }
        x = np.asarray([[-1.0], [-0.8], [1.0]], dtype=float)
        p = causal_filter(x, params)
        self.assertEqual(p.shape, (3, 2))
        self.assertTrue(np.allclose(p.sum(axis=1), 1.0))
        self.assertGreater(p[0, 0], p[0, 1])
        self.assertGreater(p[-1, 1], p[-1, 0])

    def test_only_valid_24h_four_state_candidate_promotes_descriptively(self):
        report = {
            "generated_at": "2026-08-23T00:00:00+00:00",
            "preferred_descriptive_variant": "return_24h",
            "variants": {
                "return_24h": {
                    "descriptive_candidate_ready": True,
                    "feature_schema": ["log_return_24h", "realized_volatility", "log_volume_change"],
                    "winner": {"n_states": 4, "best_bic": 1.0},
                    "winner_directional_separation": {"passes": True},
                    "winner_model_parameters": {
                        "n_states": 4,
                        "covariance_type": "diag",
                        "startprob": [0.25] * 4,
                        "transmat": [[0.25] * 4 for _ in range(4)],
                        "means": [[0.0] * 3 for _ in range(4)],
                        "covars": [[[1.0,0,0],[0,1.0,0],[0,0,1.0]] for _ in range(4)],
                    },
                    "winner_state_profiles": [{"state": i, "label": f"S{i}"} for i in range(4)],
                    "normalization": {"type": "robust_z", "clip": [-5,5], "median": [0,0,0], "scale": [1,1,1]},
                }
            },
        }
        rec = build_production_model_record(report)
        self.assertIsNotNone(rec)
        self.assertTrue(rec["descriptive_production"])
        self.assertFalse(rec["predictive_production"])


if __name__ == "__main__":
    unittest.main()
