import unittest
from eth_trend_v3.models import Factor
from eth_trend_v3.feature_cluster import cluster_factors

class TestFeatureCluster(unittest.TestCase):
    def test_correlated_momentum_features_collapse_to_one_cluster(self):
        fs=[Factor('Technical','MA',10,1,10),Factor('Technical','MACD',8,1,8),Factor('Technical','RSI',5,1,5)]
        c=cluster_factors(fs)
        self.assertEqual(set(c['momentum']['features']),{'MA','MACD','RSI'})
        self.assertEqual(c['momentum']['score'],100.0)

if __name__=='__main__': unittest.main()
