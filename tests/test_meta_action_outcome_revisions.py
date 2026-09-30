from scripts.plan_meta_action_outcome_revisions import plan_revisions
from tests.test_meta_action_outcomes import meta, monitor, pit
from eth_trend_v3.meta_action_outcomes import build_meta_action_event, build_due_meta_action_outcomes

def event():
    return build_meta_action_event(meta("ADD","HOLD",30), monitor(price=100.0,direction_4h=30),
                                   monitor_run_id=1, monitor_git_sha="old")[0]

def test_plan_revision_only_for_complete_canonical_path():
    e=event()
    records=[pit("2026-09-27T08:15:00+00:00",104), pit("2026-09-27T12:15:00+00:00",108),
             pit("2026-09-27T16:15:00+00:00",112)]
    corrected=build_due_meta_action_outcomes([e],records)
    base=dict(next(x for x in corrected if x["horizon_hours"]==12))
    base.update(path_complete=False,path_bars=12,expected_path_bars=12,mae=None,mfe=None)
    report=plan_revisions([e],[base],records,source_git_sha="newsha")
    assert report["candidate_count"] == 1
    c=report["candidates"][0]
    assert c["payload"]["path_complete"] is True
    assert c["payload"]["expected_path_bars"] == 3
    assert c["source_git_sha"] == "newsha"
    assert report["guardrails"]["base_outcomes_mutated"] is False

def test_plan_refuses_revision_when_source_pit_missing():
    e=event()
    base={"event_id":e["event_id"],"horizon_hours":12,"path_complete":False}
    records=[pit("2026-09-27T08:15:00+00:00",104), pit("2026-09-27T16:15:00+00:00",112)]
    report=plan_revisions([e],[base],records,source_git_sha="newsha")
    assert report["candidate_count"] == 0
    assert report["skipped"][0]["reason_code"] == "INCOMPLETE_CANONICAL_PATH"

def test_plan_refuses_revision_when_exact_target_missing():
    e=event()
    base={"event_id":e["event_id"],"horizon_hours":12,"path_complete":False}
    records=[pit("2026-09-27T08:15:00+00:00",104), pit("2026-09-27T12:15:00+00:00",108)]
    report=plan_revisions([e],[base],records,source_git_sha="newsha")
    assert report["candidate_count"] == 0
    assert report["skipped"][0]["reason_code"] == "MISSING_SOURCE_PIT"
