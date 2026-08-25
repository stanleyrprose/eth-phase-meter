from datetime import datetime,timedelta,timezone

import numpy as np

from eth_trend_v3.calibration_research_v2 import compare_calibration_windows
from eth_trend_v3.dynamic_baseline import BaselineSpec,predict_baseline
from eth_trend_v3.feature_ablation_research import run_group_ablation
from eth_trend_v3.promotion import GateConfig,promotion_gate
from eth_trend_v3.research_validation import purged_walk_forward
from eth_trend_v3.shadow_forecast import settle_shadow_record,shadow_metrics

UTC=timezone.utc


def _rows(n=180):
    out=[]
    for i in range(n):
        t=datetime(2025,1,1,tzinfo=UTC)+timedelta(hours=4*i); trend=np.sin(i/8); regime="A" if i%30<20 else "B"
        out.append({"feature_time":t.isoformat(),"timestamp":t.isoformat(),"available_at":t.isoformat(),"label_start_time":t.isoformat(),"label_end_time":(t+timedelta(hours=12)).isoformat(),"target_up":int(trend>0),"trend":trend,"volatility_risk":abs(np.cos(i/10)),"regime":regime})
    return out


def test_regime_and_shrunk_baselines_fallback_and_predict():
    r=_rows(); p=predict_baseline(r[:120],r[120:125],BaselineSpec("shrunk-regime",min_regime_count=5,prior_strength=20)); assert len(p)==5 and np.all((p>0)&(p<1))


def test_ablation_reports_order_robustness():
    r=_rows(); folds=purged_walk_forward(r,min_train=90,test_size=30)
    report=run_group_ablation(folds,{"trend":["trend"],"risk":["volatility_risk"]},horizon_bars=3,bootstrap_reps=20)
    assert report["order_robustness"]["checks"] and set(report["order_robustness"]["pass_rate_by_group"])=={"trend","risk"}


def test_calibration_window_selection_keeps_test_out_of_fit():
    raw=np.linspace(.1,.9,150); y=(raw>.5).astype(int); r=compare_calibration_windows(y,raw,train_end=60,test_start=100,rolling_windows=(20,30),eligible=True)
    assert r["available"] and r["winner_window"] in r["windows"]


def test_shadow_settlement_and_effective_evidence():
    t=datetime(2026,1,1,tzinfo=UTC); record={"settled":False,"settlement_time":(t+timedelta(hours=12)).isoformat(),"entry_price":100,"probability":.7,"baseline_probability":.5,"data_health":"NORMAL"}
    path=[(t+timedelta(hours=4),95),(t+timedelta(hours=8),105),(t+timedelta(hours=12),110)]
    settled=settle_shadow_record(record,path); assert settled["settled"] and settled["actual_direction"]==1
    m=shadow_metrics([settled],horizon_bars=3); assert m["effective_settled_evidence"]["kind"]=="DIAGNOSTIC"


def test_versioned_promotion_gate_enforces_effective_shadow_evidence():
    evidence={"leakage_free":True,"pit_valid":True,"registry_complete":True,"artifact_valid":True,"train_serve_parity":True,"shadow_complete":True,"data_health_normal":True,"emergency_freeze_clear":True,"research_brier_skill":.03,"shadow_brier_skill":.02,"calibration_error":.05,"effective_shadow_n":2}
    cfg=GateConfig(version="v2-test",min_effective_shadow_n=3,max_calibration_error=.1); d=promotion_gate(evidence,config=cfg)
    assert not d.eligible and d.gate_version=="v2-test" and "INSUFFICIENT_EFFECTIVE_SAMPLE" in d.reasons
