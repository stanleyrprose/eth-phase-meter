import unittest
import numpy as np
import pandas as pd

from eth_trend_v3.hmm_production import causal_filter, build_production_model_record, infer_live_regime


class HMMProductionTests(unittest.TestCase):
    def _report(self):
        cov = [np.eye(3).tolist() for _ in range(4)]
        return {
            'generated_at':'2026-08-22T00:00:00Z',
            'preferred_descriptive_variant':'return_24h',
            'variants':{
                'return_24h':{
                    'descriptive_candidate_ready':True,
                    'feature_schema':['log_return_24h','realized_volatility','log_volume_change'],
                    'winner':{'n_states':4,'best_bic':1.0},
                    'winner_directional_separation':{'passes':True},
                    'normalization':{'median':[0,0,0],'scale':[1,1,1]},
                    'winner_model_parameters':{
                        'n_states':4,'covariance_type':'diag',
                        'startprob':[0.25]*4,
                        'transmat':np.eye(4).tolist(),
                        'means':[[0,0,0],[1,0,0],[-1,0,0],[0,1,0]],
                        'covars':cov,
                    },
                    'winner_state_profiles':[
                        {'state':0,'label':'Low-Vol Bull'},
                        {'state':1,'label':'High-Vol Bull'},
                        {'state':2,'label':'Low-Vol Bear'},
                        {'state':3,'label':'High-Vol Bear'},
                    ],
                }
            }
        }

    def test_build_record_is_descriptive_only(self):
        r=build_production_model_record(self._report())
        self.assertTrue(r['descriptive_production'])
        self.assertFalse(r['predictive_production'])
        self.assertEqual(r['n_states'],4)

    def test_causal_filter_rows_sum_to_one(self):
        params=self._report()['variants']['return_24h']['winner_model_parameters']
        p=causal_filter(np.zeros((5,3)),params)
        self.assertEqual(p.shape,(5,4))
        self.assertTrue(np.allclose(p.sum(axis=1),1.0))

    def test_live_inference_uses_model_record(self):
        n=30
        candles=pd.DataFrame({'timestamp':pd.date_range('2026-01-01',periods=n,freq='4h',tz='UTC'),'close':np.linspace(100,120,n),'volume':np.linspace(1000,1500,n)})
        out=infer_live_regime({'candles':candles},build_production_model_record(self._report()))
        self.assertTrue(out['available'])
        self.assertEqual(out['engine'],'hmm-v2-production')
        self.assertAlmostEqual(sum(out['posterior']),1.0,places=6)

if __name__=='__main__': unittest.main()
