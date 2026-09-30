from scripts.evaluate_meta_action_v1 import evaluate

def ev(eid, action, reasons, d4=30, regime="TREND"):
    return {"event_id":eid,"action":action,"reason_codes":reasons,"phase_4h_direction":d4,"phase_4h_regime":regime}
def oc(eid,h,r):
    return {"event_id":eid,"horizon_hours":h,"actual_return":r,"path_complete":True,"mae":-0.01,"mfe":0.03}

def test_override_counterfactual_is_research_only_and_policy_aligned():
    events=[ev("a","ADD",["PHASE_BULLISH_TA_NEUTRAL"],35),ev("b","HOLD",["NO_CROSS_SYSTEM_EDGE"],5)]
    report=evaluate(events,[oc("a",4,.04),oc("b",4,-.01)])
    h=report["horizons"]["4"]
    assert report["research_only"] is True
    assert report["promotion_review_ready"] is False
    assert h["override_all"]["n"] == 1
    assert h["override_policy_aligned"]["mean_aligned_return"] == .04
    assert h["old_vs_new_counterfactual"]["old_rule_directional_exposure"] == "HOLD/0"
    assert report["governance"]["threshold_change"] is False

def test_bearish_override_alignment_flips_realized_return():
    events=[ev("x","REDUCE",["PHASE_BEARISH_TA_NEUTRAL"],-30,"RANGE")]
    report=evaluate(events,[oc("x",12,-.05)])
    h=report["horizons"]["12"]
    assert h["override_bearish"]["mean_return"] == -.05
    assert h["old_vs_new_counterfactual"]["new_rule_bearish_aligned_outcome"]["mean_aligned_return"] == .05
    assert h["by_4h_regime"]["RANGE"]["n"] == 1
