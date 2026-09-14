import os
import unittest
from unittest.mock import patch

from eth_trend_v3 import external_state


class TestDuneExternalState(unittest.TestCase):
    def setUp(self):
        self.old = dict(os.environ)
        self.beacon_patcher = patch("eth_trend_v3.external_state._beaconchain_queue_state", return_value={"structural": {}})
        self.beacon_patcher.start()
        self.tvl_patcher = patch(
            "eth_trend_v3.external_state._defillama_eth_tvl_state",
            return_value={"valuation": {}, "capital_flow": {}},
        )
        self.tvl_mock = self.tvl_patcher.start()
        self.inflow_patcher = patch(
            "eth_trend_v3.external_state._defillama_eth_inflows_state",
            return_value={"capital_flow": {}},
        )
        self.inflow_mock = self.inflow_patcher.start()
        for k in (
            "DUNE_API_KEY",
            "ETH_VALUATION_API_URL",
            "ETH_FLOW_API_URL",
            "ETH_STRUCTURAL_API_URL",
        ):
            os.environ.pop(k, None)

    def tearDown(self):
        self.inflow_patcher.stop()
        self.tvl_patcher.stop()
        self.beacon_patcher.stop()
        os.environ.clear()
        os.environ.update(self.old)

    @patch("eth_trend_v3.external_state._farside_eth_etf_state")
    @patch("eth_trend_v3.external_state._defillama_stablecoin_state")
    @patch("eth_trend_v3.external_state._coinmetrics_community_state")
    def test_public_baseline_works_without_dune_key(self, coinmetrics, defillama, farside):
        coinmetrics.return_value = {
            "valuation": {"mvrv": 1.2, "_source": "Coin Metrics Community"},
            "structural": {"net_issuance_eth": 2800.0, "exchange_balance_change_pct": -0.2},
        }
        defillama.return_value = {
            "capital_flow": {"stablecoin_supply_change_usd": 125000000.0, "_source": "DefiLlama"}
        }
        farside.return_value = {
            "capital_flow": {"etf_flow_usd": 184000000.0, "_source": "Farside Investors"}
        }
        r = external_state.collect_external_state()
        self.assertEqual(r["valuation"]["mvrv"], 1.2)
        self.assertEqual(r["capital_flow"]["stablecoin_supply_change_usd"], 125000000.0)
        self.assertEqual(r["capital_flow"]["etf_flow_usd"], 184000000.0)
        self.assertEqual(r["structural"]["net_issuance_eth"], 2800.0)

    @patch("eth_trend_v3.external_state._farside_eth_etf_state")
    @patch("eth_trend_v3.external_state._defillama_stablecoin_state")
    @patch("eth_trend_v3.external_state._coinmetrics_community_state")
    def test_public_tvl_enriches_valuation_and_capital_flow(self, coinmetrics, defillama, farside):
        coinmetrics.return_value = {
            "valuation": {"mvrv": 1.2, "market_cap_usd": 300_000_000_000.0},
            "capital_flow": {"exchange_netflow_eth": -5000.0},
            "structural": {},
        }
        self.tvl_mock.return_value = {
            "valuation": {"defi_tvl_usd": 50_000_000_000.0},
            "capital_flow": {"defi_tvl_change_usd": 250_000_000.0},
        }
        self.inflow_mock.return_value = {
            "capital_flow": {"defi_inflows_24h_usd": 7_500_000.0}
        }
        defillama.return_value = {
            "capital_flow": {"stablecoin_supply_change_usd": 125_000_000.0}
        }
        farside.return_value = {"capital_flow": {"etf_flow_usd": 184_000_000.0}}

        r = external_state.collect_external_state()
        self.assertEqual(r["valuation"]["mcap_to_tvl"], 6.0)
        self.assertEqual(r["capital_flow"]["defi_tvl_change_usd"], 250_000_000.0)
        self.assertEqual(r["capital_flow"]["defi_inflows_24h_usd"], 7_500_000.0)

    @patch("eth_trend_v3.external_state._farside_eth_etf_state")
    @patch("eth_trend_v3.external_state._defillama_stablecoin_state")
    @patch("eth_trend_v3.external_state._coinmetrics_community_state")
    def test_farside_failure_is_optional_when_stablecoin_flow_exists(self, coinmetrics, defillama, farside):
        coinmetrics.return_value = {"valuation": {"mvrv": 1.2}, "structural": {"net_issuance_eth": 2800.0}}
        defillama.return_value = {"capital_flow": {"stablecoin_supply_change_usd": 125000000.0}}
        farside.return_value = {"capital_flow": {"_error": "FARSIDE_ETH_TABLE_UNPARSEABLE"}}
        r = external_state.collect_external_state()
        self.assertNotIn("_error", r["capital_flow"])
        self.assertEqual(r["capital_flow"]["_provider_errors"]["farside"]["error"], "FARSIDE_ETH_TABLE_UNPARSEABLE")

    @patch("eth_trend_v3.external_state._farside_eth_etf_state")
    @patch("eth_trend_v3.external_state._defillama_stablecoin_state")
    @patch("eth_trend_v3.external_state._coinmetrics_community_state")
    @patch("eth_trend_v3.external_state._dune_execute")
    def test_dune_enriches_public_baseline_without_overwriting_semantics(self, execute, coinmetrics, defillama, farside):
        os.environ["DUNE_API_KEY"] = "test-only"
        coinmetrics.return_value = {
            "valuation": {"mvrv": 1.2},
            "capital_flow": {"exchange_netflow_eth": -5000.0, "_source": "Coin Metrics Community"},
            "structural": {"net_issuance_eth": 2800.0},
        }
        defillama.return_value = {
            "capital_flow": {"stablecoin_supply_change_usd": 125000000.0}
        }
        farside.return_value = {
            "capital_flow": {"etf_flow_usd": 184000000.0}
        }
        execute.return_value = {
            "exchange_netflow_eth": -12000.0,
            "stablecoin_flow_usd": 250000000.0,
            "staking_netflow_eth": 18000.0,
        }
        r = external_state.collect_external_state()
        self.assertEqual(r["capital_flow"]["stablecoin_supply_change_usd"], 125000000.0)
        self.assertEqual(r["capital_flow"]["stablecoin_flow_usd"], 250000000.0)
        self.assertEqual(r["capital_flow"]["exchange_netflow_eth"], -5000.0)
        self.assertEqual(r["structural"]["staking_netflow_eth"], 18000.0)
        self.assertEqual(r["valuation"]["mvrv"], 1.2)

    @patch("eth_trend_v3.external_state._farside_eth_etf_state")
    @patch("eth_trend_v3.external_state._defillama_stablecoin_state")
    @patch("eth_trend_v3.external_state._coinmetrics_community_state")
    @patch("eth_trend_v3.external_state._dune_execute")
    def test_dune_failure_is_optional_when_public_metrics_exist(self, execute, coinmetrics, defillama, farside):
        os.environ["DUNE_API_KEY"] = "test-only"
        coinmetrics.return_value = {
            "valuation": {"mvrv": 1.2},
            "structural": {"net_issuance_eth": 2800.0},
        }
        defillama.return_value = {
            "capital_flow": {"stablecoin_supply_change_usd": 125000000.0}
        }
        farside.return_value = {
            "capital_flow": {"etf_flow_usd": 184000000.0}
        }
        execute.return_value = {"_error": "DUNE_QUERY_FAILED", "message": "paid tier required"}
        r = external_state.collect_external_state()
        self.assertNotIn("_error", r["capital_flow"])
        self.assertNotIn("_error", r["structural"])
        self.assertEqual(r["capital_flow"]["_provider_errors"]["dune"]["error"], "DUNE_QUERY_FAILED")
        self.assertEqual(r["structural"]["_provider_errors"]["dune"]["error"], "DUNE_QUERY_FAILED")


if __name__ == "__main__":
    unittest.main()
