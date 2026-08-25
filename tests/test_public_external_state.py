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
                    "AdrActCnt": "800000",
                    "FeeTotNtv": "200",
                    "TxCnt": "1700000",
                },
                {
                    "time": "2026-08-24T00:00:00.000000000Z",
                    "CapMVRVCur": "1.12",
                    "SplyCur": "121983000",
                    "SplyExNtv": "15718500",
                    "AdrActCnt": "851215",
                    "FeeTotNtv": "397.47",
                    "TxCnt": "1859865",
                },
            ]
        }
        get.return_value = response

        state = external_state._coinmetrics_community_state()
        self.assertAlmostEqual(state["valuation"]["mvrv"], 1.12)
        self.assertAlmostEqual(state["structural"]["net_issuance_eth"], 3000.0)
        self.assertAlmostEqual(state["structural"]["exchange_balance_change_pct"], -0.2)
        self.assertEqual(state["structural"]["active_addresses"], 851215.0)
        self.assertEqual(state["structural"]["network_fees_eth"], 397.47)
        self.assertEqual(state["structural"]["transaction_count"], 1859865.0)
        self.assertEqual(state["valuation"]["_observed_at"], "2026-08-24T00:00:00.000000000Z")

    @patch("eth_trend_v3.external_state.requests.get")
    def test_farside_maps_latest_daily_total_and_negative_parentheses(self, get):
        response = Mock(ok=True)
        response.text = """
        <table>
          <tr><td><span class="tabletext">21 Aug 2026</span></td><td><span class="tabletext">184.0</span></td></tr>
          <tr><td><span class="tabletext">24 Aug 2026</span></td><td><span class="tabletext">(33.5)</span></td></tr>
        </table>
        """
        get.return_value = response

        flow = external_state._farside_eth_etf_state()["capital_flow"]
        self.assertEqual(flow["etf_flow_usd"], -33500000.0)
        self.assertEqual(flow["etf_flow_date"], "2026-08-24")
        self.assertIn("Farside", flow["_source"])

    @patch("eth_trend_v3.external_state.requests.get")
    def test_farside_uses_jina_reader_when_direct_page_is_bot_blocked(self, get):
        direct = Mock(ok=False, status_code=403, text="cloudflare")
        direct.json.side_effect = ValueError("not json")
        proxy = Mock(ok=True)
        proxy.text = """
        | 21 Aug 2026 | 150.8 | 9.9 | 9.6 | 2.2 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 11.5 | 184.0 |
        | 24 Aug 2026 | 90.9 | 0.0 | 6.8 | 0.9 | 0.0 | 4.5 | 0.0 | 0.0 | 0.0 | 12.5 | 115.6 |
        """
        get.side_effect = [direct, proxy]

        flow = external_state._farside_eth_etf_state()["capital_flow"]
        self.assertEqual(flow["etf_flow_usd"], 115600000.0)
        self.assertEqual(flow["etf_flow_date"], "2026-08-24")
        self.assertIn("via Jina Reader", flow["_source"])
        self.assertEqual(get.call_count, 2)

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
