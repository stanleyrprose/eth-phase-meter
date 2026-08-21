import unittest
from datetime import datetime, timezone, timedelta
from eth_trend_v3.data_health import assess

class TestDataHealth(unittest.TestCase):
    def test_coverage_below_50_fails_closed(self):
        self.assertEqual(assess({},49)['status'],'DATA_INSUFFICIENT')
    def test_stale_data_degrades(self):
        old=(datetime.now(timezone.utc)-timedelta(days=10)).isoformat()
        raw={'candles':{'x':1},'_meta':{'candles':{'observed_at':old}}}
        h=assess(raw,80)
        self.assertEqual(h['status'],'DEGRADED')
        self.assertIn('candles',h['stale_sources'])

if __name__=='__main__': unittest.main()
