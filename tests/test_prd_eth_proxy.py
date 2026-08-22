import unittest
from eth_trend_v3.eth_proxy_validation import validate_proxy

class TestEthProxy(unittest.TestCase):
    def test_insufficient_benchmark_data_stays_gated(self):
        r=validate_proxy([1,2,3],[1,2,3])
        self.assertEqual(r['status'],'GATED')
        self.assertFalse(r['kill'])
    def test_bad_proxy_hits_kill_criteria(self):
        a=list(range(100)); b=list(reversed(range(100)))
        r=validate_proxy(a,b,min_n=60)
        self.assertEqual(r['status'],'KILL')
        self.assertTrue(r['kill'])

if __name__=='__main__': unittest.main()
