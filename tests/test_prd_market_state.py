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

if __name__=='__main__': unittest.main()
