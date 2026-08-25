import unittest
from unittest.mock import Mock, patch

from eth_trend_v3 import external_state


class TestPublicExternalState(unittest.TestCase):
    @patch("eth_trend_v3.external_state.requests.get")
    def test_coinmetrics_maps_mvrv_and_daily_supply_changes(self, get):
        response = Mock(ok=True)
        response.json.return_value = {
            "data": [
                {
                    "time": "2026-08-23T00:00:00.000000000Z",
                    "CapMVRVCur": "1.10",
                    "SplyCur": "121980000",
                    "SplyExNtv": "15750000",
                },
                {
                    "time": "2026-08-24T00:00:00.000000000Z",
                    "CapMVRVCur": "1.12",
                    "SplyCur": "121983000",
                    "SplyExNtv": "15718500",
                },
            ]
        }
        get.return_value = response

        state = external_state._coinmetrics_community_state()
        self.assertAlmostEqual(state["valuation"]["mvrv"], 1.12)
        self.assertAlmostEqual(state["structural"]["net_issuance_eth"], 3000.0)
        self.assertAlmostEqual(state["structural"]["exchange_balance_change_pct"], -0.2)
        self.assertEqual(state["valuation"]["_observed_at"], "2026-08-24T00:00:00.000000000Z")

    @patch("eth_trend_v3.external_state.requests.get")
    def test_defillama_supply_change_stays_distinct_from_cex_flow(self, get):
        response = Mock(ok=True)
        response.json.return_value = [
            {"date": "1787529600", "totalCirculatingUSD": {"peggedUSD": 147500000000}},
            {"date": "1787616000", "totalCirculatingUSD": {"peggedUSD": 148000000000}},
        ]
        get.return_value = response

        flow = external_state._defillama_stablecoin_state()["capital_flow"]
        self.assertEqual(flow["stablecoin_supply_change_usd"], 500000000.0)
        self.assertNotIn("stablecoin_flow_usd", flow)
        self.assertIn("DefiLlama", flow["_source"])


if __name__ == "__main__":
    unittest.main()
