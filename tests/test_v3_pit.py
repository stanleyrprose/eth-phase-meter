import unittest
from types import SimpleNamespace
from eth_trend_v3.pit import payload_hash, build_pit_record


class TestPIT(unittest.TestCase):
    def test_hash_is_deterministic(self):
        self.assertEqual(payload_hash({'b': 2, 'a': 1}), payload_hash({'a': 1, 'b': 2}))

    def test_record_contains_traceability_fields(self):
        result = SimpleNamespace(timestamp='2026-08-21 08:00 UTC', price=2500.0, state='NEUTRAL', regime='RANGE', final_direction=0, available_bias=0, coverage=80)
        r = build_pit_record('4h', {'x': 1}, result)
        for key in ('event_time','observed_at','raw_payload','raw_payload_hash','coverage','parser_version','feature_version','model_version','config_version'):
            self.assertIn(key, r)


if __name__ == '__main__':
    unittest.main()
