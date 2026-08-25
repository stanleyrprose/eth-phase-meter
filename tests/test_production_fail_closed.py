import unittest
from unittest.mock import patch

from eth_trend_v3.runner import _forecast_bundle


class TestProductionFailClosed(unittest.TestCase):
    @patch("eth_trend_v3.production_runtime.load_production_model", return_value=None)
    def test_runner_does_not_fit_research_model_for_live_probability(self, _mock):
        market_state={"dimensions":{"trend":{"score":1.0},"valuation":{"score":0.0},"capital_flow":{"score":0.0},"crowding":{"score":0.0},"structural_supply":{"score":0.0},"volatility_risk":{"score":1.0}}}
        health={"status":"NORMAL","coverage":100}
        forecasts,reliability=_forecast_bundle([],market_state,health,{"regime":"Transition"})
        self.assertEqual(reliability,"Low")
        for item in forecasts.values():
            self.assertIsNone(item["probability_up"])
            self.assertEqual(item["status"],"UNAVAILABLE")
            self.assertEqual(item["reason"],"NO_PRODUCTION_MODEL_APPROVED")


if __name__=="__main__": unittest.main()
