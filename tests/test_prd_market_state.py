import unittest
from types import SimpleNamespace

from eth_trend_v3.market_state import build_market_state


def _result():
    return SimpleNamespace(
        quality={
            "families": {
                "Technical": {
                    "nominal": 40,
                    "active": 40,
                    "coverage": 100,
                    "contribution": 20,
                }
            }
        },
        crowding=50,
        volatility=30,
    )


class TestMarketState(unittest.TestCase):
    def test_six_dimensions_exist_and_missing_structural_is_not_zero(self):
        state = build_market_state(
            {"valuation": {}, "capital_flow": {}, "structural": {}}, _result()
        )
        self.assertEqual(
            set(state["dimensions"]),
            {
                "trend",
                "valuation",
                "capital_flow",
                "crowding",
                "structural_supply",
                "volatility_risk",
            },
        )
        self.assertIsNone(state["dimensions"]["valuation"]["score"])
        self.assertIsNone(state["dimensions"]["structural_supply"]["score"])
        self.assertEqual(state["dimensions"]["trend"]["score"], 50)

    def test_valuation_v2_uses_two_independent_primary_slots(self):
        one = build_market_state(
            {"valuation": {"mvrv": 1.2}, "capital_flow": {}, "structural": {}},
            _result(),
        )["dimensions"]["valuation"]
        both = build_market_state(
            {
                "valuation": {"mvrv": 1.2, "mcap_to_tvl": 6.0},
                "capital_flow": {},
                "structural": {},
            },
            _result(),
        )["dimensions"]["valuation"]
        self.assertEqual(one["coverage"], 50)
        self.assertEqual(both["coverage"], 100)

    def test_correlated_legacy_valuation_aliases_do_not_inflate_coverage(self):
        valuation = build_market_state(
            {
                "valuation": {
                    "price_realized_ratio": 1.2,
                    "nupl": 0.3,
                },
                "capital_flow": {},
                "structural": {},
            },
            _result(),
        )["dimensions"]["valuation"]
        self.assertEqual(valuation["coverage"], 50)

    def test_stablecoin_supply_change_is_separate_capital_flow_component(self):
        state = build_market_state(
            {
                "valuation": {},
                "capital_flow": {"stablecoin_supply_change_usd": 500_000_000},
                "structural": {},
            },
            _result(),
        )
        flow = state["dimensions"]["capital_flow"]
        self.assertEqual(flow["score"], 100)
        self.assertEqual(flow["coverage"], 25)

    def test_three_independent_capital_flow_components_give_75pct_coverage(self):
        state = build_market_state(
            {
                "valuation": {},
                "capital_flow": {
                    "etf_flow_usd": 115_600_000,
                    "exchange_netflow_eth": -18_166,
                    "stablecoin_supply_change_usd": 484_900_000,
                },
                "structural": {},
            },
            _result(),
        )
        self.assertEqual(state["dimensions"]["capital_flow"]["coverage"], 75)

    def test_four_free_capital_flow_components_give_100pct_coverage(self):
        state = build_market_state(
            {
                "valuation": {},
                "capital_flow": {
                    "etf_flow_usd": 115_600_000,
                    "exchange_netflow_eth": -18_166,
                    "stablecoin_supply_change_usd": 484_900_000,
                    "defi_inflows_24h_usd": 250_000_000,
                },
                "structural": {},
            },
            _result(),
        )
        self.assertEqual(state["dimensions"]["capital_flow"]["coverage"], 100)

    def test_optional_dune_stablecoin_cex_flow_does_not_inflate_primary_coverage(self):
        state = build_market_state(
            {
                "valuation": {},
                "capital_flow": {"stablecoin_flow_usd": 500_000_000},
                "structural": {},
            },
            _result(),
        )
        flow = state["dimensions"]["capital_flow"]
        self.assertIsNone(flow["score"])
        self.assertEqual(flow["coverage"], 0)

    def test_tvl_change_is_diagnostic_only_and_does_not_inflate_capital_flow_coverage(self):
        state = build_market_state(
            {
                "valuation": {},
                "capital_flow": {"defi_tvl_change_usd": 500_000_000},
                "structural": {},
            },
            _result(),
        )
        flow = state["dimensions"]["capital_flow"]
        self.assertIsNone(flow["score"])
        self.assertEqual(flow["coverage"], 0)

    def test_staking_queue_plus_supply_metrics_gives_full_structural_coverage(self):
        state = build_market_state(
            {
                "valuation": {},
                "capital_flow": {},
                "structural": {
                    "net_issuance_eth": 3000,
                    "exchange_balance_change_pct": -0.2,
                    "staking_queue_imbalance_pct": 90,
                },
            },
            _result(),
        )
        structural = state["dimensions"]["structural_supply"]
        self.assertEqual(structural["coverage"], 100)
        self.assertGreater(structural["score"], 0)

    def test_realized_staking_flow_takes_precedence_over_queue_proxy(self):
        state = build_market_state(
            {
                "valuation": {},
                "capital_flow": {},
                "structural": {
                    "staking_netflow_eth": -50000,
                    "staking_queue_imbalance_pct": 100,
                },
            },
            _result(),
        )
        structural = state["dimensions"]["structural_supply"]
        self.assertAlmostEqual(structural["coverage"], 100 / 3)
        self.assertEqual(structural["score"], -100)

    def test_optional_bridge_flow_does_not_inflate_structural_coverage(self):
        state = build_market_state(
            {
                "valuation": {},
                "capital_flow": {},
                "structural": {"l2_bridge_netflow_eth": 100000},
            },
            _result(),
        )
        structural = state["dimensions"]["structural_supply"]
        self.assertEqual(structural["coverage"], 0)
        self.assertIsNone(structural["score"])

    def test_dimension_schema_versions_are_bumped_for_new_semantics(self):
        state = build_market_state(
            {"valuation": {}, "capital_flow": {}, "structural": {}}, _result()
        )
        self.assertEqual(state["dimension_versions"]["valuation"], "valuation-v2-defi-tvl")
        self.assertEqual(state["dimension_versions"]["capital_flow"], "capital-flow-v3-usd-inflows")
        self.assertEqual(
            state["dimension_versions"]["structural_supply"],
            "structural-supply-v3-free-baseline",
        )


if __name__ == "__main__":
    unittest.main()
