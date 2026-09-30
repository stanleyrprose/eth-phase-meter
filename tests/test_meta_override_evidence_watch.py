from scripts.meta_override_evidence_watch import override_count,reached_checkpoint

def test_override_count_counts_independent_events_not_outcomes():
    events=[
      {"reason_codes":["PHASE_BULLISH_TA_NEUTRAL"]},
      {"reason_codes":["PHASE_BEARISH_TA_NEUTRAL"]},
      {"reason_codes":["NO_CROSS_SYSTEM_EDGE"]},
    ]
    assert override_count(events)==2

def test_checkpoints_only_fire_once_and_can_skip_forward():
    assert reached_checkpoint(0,0) is None
    assert reached_checkpoint(1,0)==1
    assert reached_checkpoint(4,1) is None
    assert reached_checkpoint(5,1)==5
    assert reached_checkpoint(21,10)==20
    assert reached_checkpoint(30,20)==30
    assert reached_checkpoint(40,30) is None
