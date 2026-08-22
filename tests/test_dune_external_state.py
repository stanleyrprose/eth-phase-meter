import os
import unittest
from unittest.mock import patch

from eth_trend_v3 import external_state


class TestDuneExternalState(unittest.TestCase):
    def setUp(self):
        self.old = dict(os.environ)
        for k in (
            "DUNE_API_KEY",
            "ETH_VALUATION_API_URL",
            "ETH_FLOW_API_URL",
            "ETH_STRUCTURAL_API_URL",
        ):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)

    def test_missing_dune_key_keeps_metrics_missing(self):
        r = external_state.collect_external_state()
        self.assertEqual(r, {"valuation": {}, "capital_flow": {}, "structural": {}})

    @patch("eth_trend_v3.external_state._dune_execute")
    def test_dune_maps_curated_metrics_without_fabricating_valuation(self, execute):
        os.environ["DUNE_API_KEY"] = "test-only"
        execute.return_value = {
            "exchange_netflow_eth": -12000.0,
            "stablecoin_flow_usd": 250000000.0,
            "staking_netflow_eth": 18000.0,
        }
        r = external_state.collect_external_state()
        self.assertEqual(r["valuation"], {})
        self.assertEqual(r["capital_flow"]["exchange_netflow_eth"], -12000.0)
        self.assertEqual(r["capital_flow"]["stablecoin_flow_usd"], 250000000.0)
        self.assertEqual(r["structural"]["staking_netflow_eth"], 18000.0)

    @patch("eth_trend_v3.external_state._dune_execute")
    def test_dune_failure_is_error_not_zero(self, execute):
        os.environ["DUNE_API_KEY"] = "test-only"
        execute.return_value = {"_error": "DUNE_QUERY_FAILED", "message": "bad query"}
        r = external_state.collect_external_state()
        self.assertEqual(r["capital_flow"]["_error"], "DUNE_QUERY_FAILED")
        self.assertNotIn("exchange_netflow_eth", r["capital_flow"])
        self.assertEqual(r["structural"]["_error"], "DUNE_QUERY_FAILED")


if __name__ == "__main__":
    unittest.main()
