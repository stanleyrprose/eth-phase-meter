import unittest
from types import SimpleNamespace
from eth_trend_v3.market_state import build_market_state

class TestMarketState(unittest.TestCase):
    def test_six_dimensions_exist_and_missing_structural_is_not_zero(self):
        r=SimpleNamespace(quality={'families':{'Technical':{'nominal':40,'active':40,'coverage':100,'contribution':20}}},crowding=50,volatility=30)
        state=build_market_state({'valuation':{},'capital_flow':{},'structural':{}},r)
        self.assertEqual(set(state['dimensions']),{'trend','valuation','capital_flow','crowding','structural_supply','volatility_risk'})
        self.assertIsNone(state['dimensions']['valuation']['score'])
        self.assertIsNone(state['dimensions']['structural_supply']['score'])
        self.assertEqual(state['dimensions']['trend']['score'],50)

    def test_stablecoin_supply_change_is_separate_capital_flow_component(self):
        r=SimpleNamespace(quality={'families':{'Technical':{'nominal':40,'active':40,'coverage':100,'contribution':20}}},crowding=50,volatility=30)
        state=build_market_state({'valuation':{},'capital_flow':{'stablecoin_supply_change_usd':500_000_000},'structural':{}},r)
        flow=state['dimensions']['capital_flow']
        self.assertEqual(flow['score'],100)
        self.assertEqual(flow['coverage'],25)

    def test_three_independent_capital_flow_components_give_75pct_coverage(self):
        r=SimpleNamespace(quality={'families':{'Technical':{'nominal':40,'active':40,'coverage':100,'contribution':20}}},crowding=50,volatility=30)
        state=build_market_state({'valuation':{},'capital_flow':{'etf_flow_usd':115_600_000,'exchange_netflow_eth':-18_166,'stablecoin_supply_change_usd':484_900_000},'structural':{}},r)
        flow=state['dimensions']['capital_flow']
        self.assertEqual(flow['coverage'],75)


    def test_staking_queue_is_independent_structural_fallback_and_gives_third_slot(self):
        r=SimpleNamespace(quality={'families':{'Technical':{'nominal':40,'active':40,'coverage':100,'contribution':20}}},crowding=50,volatility=30)
        state=build_market_state({
            'valuation':{},
            'capital_flow':{},
            'structural':{
                'net_issuance_eth':3000,
                'exchange_balance_change_pct':-0.2,
                'staking_queue_imbalance_pct':90,
            },
        },r)
        structural=state['dimensions']['structural_supply']
        self.assertEqual(structural['coverage'],75)
        self.assertGreater(structural['score'],0)

    def test_realized_staking_flow_takes_precedence_over_queue_proxy(self):
        r=SimpleNamespace(quality={'families':{'Technical':{'nominal':40,'active':40,'coverage':100,'contribution':20}}},crowding=50,volatility=30)
        state=build_market_state({
            'valuation':{}, 'capital_flow':{},
            'structural':{'staking_netflow_eth':-50000,'staking_queue_imbalance_pct':100},
        },r)
        structural=state['dimensions']['structural_supply']
        self.assertEqual(structural['coverage'],25)
        self.assertEqual(structural['score'],-100)

if __name__=='__main__': unittest.main()
