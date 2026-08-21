import unittest
from eth_trend_v3.models import Factor
from eth_trend_v3.quality import summarize_factors
class TestV3Core(unittest.TestCase):
    def test_full_weight_scale(self):
        fs=[Factor('Technical','x',40,1,40),Factor('Derivatives','x',25,1,25),Factor('Options','x',10,1,10),Factor('Sentiment','x',5,1,5),Factor('Macro','x',20,1,20)]; q=summarize_factors(fs); self.assertEqual(q['coverage'],100.0); self.assertEqual(q['final_direction'],100)
    def test_missing_not_renormalized(self):
        fs=[Factor('Technical','x',40,1,40),Factor('Derivatives','x',25,None,0,status='UNAVAILABLE'),Factor('Options','x',10,0,0),Factor('Sentiment','x',5,0,0),Factor('Macro','x',20,0,0)]; q=summarize_factors(fs); self.assertEqual(q['final_direction'],40); self.assertEqual(q['available_bias'],53); self.assertEqual(q['coverage'],75.0)
if __name__=='__main__':unittest.main()
