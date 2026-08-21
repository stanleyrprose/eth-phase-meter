import unittest
from eth_trend_v3.dataset import build_labeled_rows

class TestLeakage(unittest.TestCase):
    def _r(self,ts,price):
        return {'observed_at':ts,'metric_value':{'timeframe':'4h','price':price},'coverage':100,'market_state_vector':{'dimensions':{'trend':{'score':1},'valuation':{'score':1},'capital_flow':{'score':1},'crowding':{'score':1},'structural_supply':{'score':1},'volatility_risk':{'score':1}}},'regime':{'regime':'Low-Vol Bull'}}
    def test_target_timestamp_is_after_prediction_timestamp(self):
        records=[self._r('2026-01-01T00:00:00+00:00',100),self._r('2026-01-04T00:00:00+00:00',110),self._r('2026-01-07T00:00:00+00:00',90)]
        rows=build_labeled_rows(records,72,tolerance_hours=1)
        self.assertTrue(rows)
        for r in rows:
            self.assertGreater(r['future_timestamp'],r['timestamp'])

if __name__=='__main__': unittest.main()
