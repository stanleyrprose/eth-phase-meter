import unittest
from eth_trend_v3.forecast import fit_live_probability, expanding_walk_forward

class TestForecastGate(unittest.TestCase):
    def test_small_sample_never_emits_probability(self):
        rows=[{'trend':float(i%5),'crowding':20.0,'volatility_risk':30.0,'target_up':i%2} for i in range(50)]
        p,wf,reason=fit_live_probability(rows,{'trend':1.0,'crowding':20.0,'volatility_risk':30.0})
        self.assertIsNone(p)
        self.assertIn(reason,('NO_MODEL_PASSED_BASE_RATE','INSUFFICIENT_CALIBRATION_DATA'))
    def test_walk_forward_reports_calibration_metrics_when_available(self):
        rows=[]
        for i in range(220):
            trend=float((i%20)-10); rows.append({'trend':trend,'target_up':1 if trend>0 else 0})
        r=expanding_walk_forward(rows,['trend'],min_train=120,test_size=20)
        self.assertTrue(r['available'])
        m=r['metrics']
        for key in ('brier','log_loss','accuracy','precision','recall','calibration_error','base_rate_lift_pp'):
            self.assertIn(key,m)

if __name__=='__main__': unittest.main()
