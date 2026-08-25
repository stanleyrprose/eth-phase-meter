from datetime import datetime,timedelta,timezone

import numpy as np
import pandas as pd
import pytest

from eth_trend_v3.calibration_research_v2 import compare_calibration
from eth_trend_v3.dynamic_baseline import BaselineSpec,predict_baseline,evaluate_baselines
from eth_trend_v3.horizon_features import build_horizon_features,correlation_audit
from eth_trend_v3.probabilistic_research import controlled_interactions,evaluate_logistic
from eth_trend_v3.promotion import emergency_override,promotion_gate,reliability
from eth_trend_v3.regime_conditioning import align_states,shrunk_regime_probability
from eth_trend_v3.research_validation import purged_walk_forward
from eth_trend_v3.shadow_forecast import path_outcome,shadow_metrics,unified_inference

UTC=timezone.utc

def rows(n=220,hours=4,label_h=12):
    out=[]
    for i in range(n):
        t=datetime(2025,1,1,tzinfo=UTC)+timedelta(hours=hours*i)
        x=np.sin(i/9); y=int((x+0.15*np.sin(i/3))>0)
        out.append({"feature_time":t.isoformat(),"timestamp":t.isoformat(),"available_at":t.isoformat(),"label_start_time":t.isoformat(),"label_end_time":(t+timedelta(hours=label_h)).isoformat(),"horizon":"3d","target_up":y,"trend":x,"volatility_risk":abs(np.cos(i/11)),"macro":np.sin(i/30)})
    return out


def test_dynamic_baselines_are_train_only_and_evaluable():
    r=rows(); folds=purged_walk_forward(r,min_train=100,test_size=30)
    report=evaluate_baselines(folds,horizon_bars=3,bootstrap_reps=50)
    assert report["available"] and report["winner"] in report["metrics"]
    p=predict_baseline(r[:100],r[100:105],BaselineSpec("rolling",window_days=90)); assert len(p)==5


def test_horizon_feature_builder_uses_backward_macro_join():
    ts=pd.date_range("2025-01-01",periods=220,freq="4h",tz="UTC"); c=pd.DataFrame({"timestamp":ts,"close":100*np.exp(np.cumsum(np.full(220,.001))),"volume":np.arange(220)+100})
    m=pd.DataFrame({"available_at":[ts[100]],"dxy_return":[.2]})
    f=build_horizon_features(c,"3d",m); assert "return_3d" in f and pd.isna(f.loc[99,"dxy_return"]) and f.loc[101,"dxy_return"]==.2


def test_controlled_interaction_budget_and_logistic_oos():
    r=rows(); folds=purged_walk_forward(r,min_train=100,test_size=30)
    pairs=controlled_interactions(["trend","volatility_risk","macro"],max_interactions=2); assert len(pairs)<=2
    report=evaluate_logistic(folds,["trend","volatility_risk"],horizon_bars=3,bootstrap_reps=50); assert report["available"]


def test_regime_alignment_and_shrinkage():
    ref=[{"mean_return":-1,"volatility":2},{"mean_return":1,"volatility":1}]; new=list(reversed(ref)); mapping=align_states(ref,new); assert mapping[1]==0 and mapping[0]==1
    p=shrunk_regime_probability([1,0,1,1],["A","B","A","A"],"A",prior_strength=20); assert 0<p<1


def test_calibration_respects_eligibility_and_none_candidate():
    raw=np.linspace(.2,.8,60); y=(raw>.5).astype(int)
    assert compare_calibration(y,raw,raw,y,eligible=False)["reason"]=="CALIBRATION_NOT_ELIGIBLE"
    assert compare_calibration(y,raw,raw,y,eligible=True)["available"]


def test_shadow_path_metrics_and_data_health_segmentation():
    out=path_outcome(100,[95,90,105,110]); assert out["mae"]<=-.1 and out["mfe"]>=.1
    rec=[{"settled":True,"data_health":"NORMAL","actual_direction":1,"probability":.7,"baseline_probability":.5},{"settled":True,"data_health":"DEGRADED","actual_direction":0,"probability":.8,"baseline_probability":.5}]
    m=shadow_metrics(rec); assert m["settled_n"]==1 and m["degraded_excluded"]==1
    assert unified_inference(lambda _: .6,{},mode="SHADOW")==.6


def test_promotion_hard_gate_and_manual_override_cannot_promote():
    evidence={"leakage_free":True,"pit_valid":True,"registry_complete":True,"artifact_valid":True,"train_serve_parity":True,"shadow_complete":True,"data_health_normal":True,"emergency_freeze_clear":True,"effective_shadow_confirmed":True,"research_brier_skill":.03,"shadow_brier_skill":.02,"data_health":"NORMAL","calibration_error":.08}
    d=promotion_gate(evidence); assert d.eligible and reliability(evidence)=="MEDIUM"
    with pytest.raises(ValueError): emergency_override("PROMOTE",operator="x",reason="no")
