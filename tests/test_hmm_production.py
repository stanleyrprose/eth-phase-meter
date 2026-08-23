import unittest
import numpy as np
import pandas as pd

from eth_trend_v3.hmm_production import causal_filter, build_production_model_record, infer_live_regime


class HMMProductionTests(unittest.TestCase):
    def _report(self):
        return {
            "generated_at": "2026-08-22T00:00:00+00:00",
            "preferred_descriptive_variant": "return_24h",
            "variants": {
                "return_24h": {
                    "descriptive_candidate_ready": True,
                    "feature_schema": ["log_return_24h", "realized_volatility", "log_volume_change"],
                    "winner": {"n_states": 4, "best_bic": 100.0},
                    "winner_directional_separation": {"passes": True},
                    "normalization": {"type":"robust_z","clip":[-5,5],"median":[0,0,0],"scale":[1,1,1]},
                    "winner_model_parameters": {
                        "n_states":4,"covariance_type":"diag",
                        "startprob":[0.25]*4,
                        "transmat":[[0.9,0.05,0.03,0.02],[0.05,0.9,0.03,0.02],[0.02,0.03,0.9,0.05],[0.02,0.03,0.05,0.9]],
                        "means":[[1,1,0],[0.2,0.2,0],[-0.2,0.5,0],[-1,1,0]],
                        "covars":[[0.2,0.2,1]]*4,
                    },
                    "winner_state_profiles": [
                        {"state":0,"label":"High-Vol Bull"}, {"state":1,"label":"Low-Vol Bull"},
                        {"state":2,"label":"Low-Vol Bear"}, {"state":3,"label":"High-Vol Bear"},
                    ],
                }
            },
        }

    def test_production_record_requires_validated_24h_four_state(self):
        rec = build_production_model_record(self._report())
        self.assertIsNotNone(rec)
        self.assertTrue(rec["descriptive_production"])
        self.assertFalse(rec["predictive_production"])

    def test_causal_filter_is_normalized(self):
        rec = build_production_model_record(self._report())
        x = np.array([[0.1,0.2,0.0],[0.5,0.7,0.1],[-0.4,0.6,-0.1]])
        p = causal_filter(x, rec["model_parameters"])
        self.assertEqual(p.shape, (3,4))
        np.testing.assert_allclose(p.sum(axis=1), np.ones(3), atol=1e-8)

    def test_live_inference_uses_production_model(self):
        rec = build_production_model_record(self._report())
        n=30
        close=np.exp(np.linspace(0,0.12,n))*2000
        volume=np.linspace(100,130,n)
        raw={"candles":pd.DataFrame({"timestamp":pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),"close":close,"volume":volume})}
        out=infer_live_regime(raw, rec)
        self.assertTrue(out["available"])
        self.assertEqual(out["engine"], "hmm-v2-production")
        self.assertEqual(len(out["posterior"]),4)
        self.assertAlmostEqual(sum(out["posterior"]),1.0,places=6)


if __name__ == "__main__":
    unittest.main()
