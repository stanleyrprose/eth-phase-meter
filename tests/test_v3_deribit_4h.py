import unittest
from unittest.mock import patch
import github_actions_runner as gar


class TestDeribit4hFallback(unittest.TestCase):
    def test_4h_is_aggregated_from_hourly_candles(self):
        base = 1_699_920_000_000
        ticks = [base + i * 3600_000 for i in range(8)]
        result = {
            'ticks': ticks,
            'open': [100 + i for i in range(8)],
            'high': [101 + i for i in range(8)],
            'low': [99 + i for i in range(8)],
            'close': [100.5 + i for i in range(8)],
            'volume': [1] * 8,
        }
        with patch.object(gar.meter, 'safe_get', return_value={'result': result}) as safe_get:
            df = gar._deribit_chart('4h', 10)
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 2)
        self.assertEqual(safe_get.call_args.args[1]['resolution'], '60')
        self.assertAlmostEqual(float(df.iloc[0]['high']), 104.0)
        self.assertAlmostEqual(float(df.iloc[0]['low']), 99.0)
        self.assertAlmostEqual(float(df.iloc[1]['high']), 108.0)
        self.assertAlmostEqual(float(df.iloc[1]['low']), 103.0)


if __name__ == '__main__':
    unittest.main()
