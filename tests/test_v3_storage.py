import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from eth_trend_v3.storage import update_history

class TestV3Storage(unittest.TestCase):
    def test_future_4h_outcome_is_backfilled(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'h.csv'
            a=SimpleNamespace(timestamp='2026-08-21 00:00 UTC',timeframe='4h',price=100.0,final_direction=30,available_bias=40,coverage=75,crowding=20,volatility=30,regime='TREND_UP',state='WEAK_BULL')
            b=SimpleNamespace(timestamp='2026-08-21 04:00 UTC',timeframe='4h',price=105.0,final_direction=40,available_bias=50,coverage=80,crowding=25,volatility=35,regime='TREND_UP',state='WEAK_BULL')
            update_history(p,a); update_history(p,b)
            with p.open(newline='',encoding='utf-8') as f: rows=list(csv.DictReader(f))
            self.assertAlmostEqual(float(rows[0]['future_4h_return']),5.0,places=5)

if __name__=='__main__': unittest.main()
