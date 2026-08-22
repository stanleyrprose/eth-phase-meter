from __future__ import annotations
import numpy as np

MODEL_LADDER=[
 ('base-rate',[]),
 ('price-momentum',['trend']),
 ('technical-risk',['trend','crowding','volatility_risk']),
 ('plus-regime',['trend','crowding','volatility_risk','regime_code']),
 ('plus-capital-flow',['trend','crowding','volatility_risk','regime_code','capital_flow']),
 ('plus-structural',['trend','crowding','volatility_risk','regime_code','capital_flow','structural_supply']),
 ('plus-valuation',['trend','crowding','volatility_risk','regime_code','capital_flow','structural_supply','valuation']),
]

def _matrix(rows,features):
    usable=[]
    for r in rows:
        vals=[r.get(f) for f in features]
        if any(v is None or not np.isfinite(v) for v in vals): continue
        usable.append(r)
    X=np.asarray([[r[f] for f in features] for r in usable],dtype=float) if features else np.empty((len(usable),0)); y=np.asarray([r['target_up'] for r in usable],dtype=int)
    return usable,X,y

def _brier(y,p): return float(np.mean((p-y)**2))
def _logloss(y,p): p=np.clip(p,1e-6,1-1e-6); return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def _classification(y,p):
    pred=(p>=.5).astype(int); tp=int(((pred==1)&(y==1)).sum()); fp=int(((pred==1)&(y==0)).sum()); fn=int(((pred==0)&(y==1)).sum())
    return {'accuracy':float(np.mean(pred==y)),'precision':tp/(tp+fp) if tp+fp else 0.0,'recall':tp/(tp+fn) if tp+fn else 0.0}
def calibration_bins(y,p,bins=5):
    out=[]; edges=np.linspace(0,1,bins+1)
    for lo,hi in zip(edges[:-1],edges[1:]):
        mask=(p>=lo)&(p<(hi if hi<1 else hi+1e-9)); n=int(mask.sum())
        if n: out.append({'lo':round(float(lo),2),'hi':round(float(hi),2),'n':n,'predicted':round(float(p[mask].mean()),4),'actual':round(float(y[mask].mean()),4)})
    return out
def _calibration_error(bins):
    n=sum(x['n'] for x in bins)
    return sum(x['n']*abs(x['predicted']-x['actual']) for x in bins)/n if n else None

def expanding_walk_forward(rows,features=None,min_train=120,test_size=24):
    features=['trend'] if features is None else features; usable,X,y=_matrix(rows,features)
    if len(y)<min_train+test_size: return {'available':False,'reason':'INSUFFICIENT_CALIBRATION_DATA','sample_size':len(y),'features':features}
    pred=[]; actual=[]; base=[]
    if not features:
        for start in range(min_train,len(y),test_size):
            end=min(len(y),start+test_size); p=float(y[:start].mean()); pred.extend([p]*(end-start)); actual.extend(y[start:end].tolist()); base.extend([p]*(end-start))
    else:
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.isotonic import IsotonicRegression
            from sklearn.preprocessing import StandardScaler
        except Exception: return {'available':False,'reason':'SKLEARN_UNAVAILABLE','sample_size':len(y),'features':features}
        for start in range(min_train,len(y),test_size):
            end=min(len(y),start+test_size); cal_n=max(20,int(start*.2)); fit_end=start-cal_n
            if fit_end<50 or len(np.unique(y[:fit_end]))<2 or len(np.unique(y[fit_end:start]))<2: continue
            scaler=StandardScaler().fit(X[:fit_end]); model=LogisticRegression(max_iter=1000,C=.5).fit(scaler.transform(X[:fit_end]),y[:fit_end]); raw_cal=model.predict_proba(scaler.transform(X[fit_end:start]))[:,1]; iso=IsotonicRegression(out_of_bounds='clip').fit(raw_cal,y[fit_end:start]); raw=model.predict_proba(scaler.transform(X[start:end]))[:,1]; pp=iso.predict(raw)
            pred.extend(pp.tolist()); actual.extend(y[start:end].tolist()); base.extend([float(y[:start].mean())]*(end-start))
    if not pred: return {'available':False,'reason':'NO_VALID_WALK_FORWARD_SPLITS','sample_size':len(y),'features':features}
    p=np.asarray(pred); yy=np.asarray(actual); bp=np.asarray(base); b=_brier(yy,p); bb=_brier(yy,bp); bins=calibration_bins(yy,p); cls=_classification(yy,p); base_rate=float(yy.mean())
    metrics={'brier':b,'log_loss':_logloss(yy,p),**cls,'base_rate':base_rate,'base_rate_brier':bb,'base_rate_accuracy':float(np.mean((bp>=.5)==yy)),'base_rate_lift_pp':100*(cls['accuracy']-max(base_rate,1-base_rate)),'brier_lift':float(bb-b),'calibration':bins,'calibration_error':_calibration_error(bins),'oos_n':len(yy)}; metrics['passes_baseline_gate']=bool(features and metrics['brier_lift']>0 and metrics['oos_n']>=60)
    return {'available':True,'sample_size':len(y),'metrics':metrics,'features':features}

def evaluate_model_ladder(rows):
    results=[]; selected=None; previous_brier=None
    for name,features in MODEL_LADDER:
        r=expanding_walk_forward(rows,features); m=r.get('metrics') or {}; b=m.get('brier'); incremental=(previous_brier-b) if previous_brier is not None and b is not None else None; entry={'name':name,'features':features,'result':r,'incremental_brier':incremental}; results.append(entry)
        if name=='base-rate':
            if b is not None: previous_brier=b
            continue
        if r.get('available') and m.get('passes_baseline_gate') and (incremental is None or incremental>0): selected=entry; previous_brier=b
        elif selected is not None: break
    return selected,results

def fit_live_probability(rows,current_features:dict):
    selected,ladder=evaluate_model_ladder(rows)
    if selected is None: return None,{'available':False,'reason':'NO_MODEL_PASSED_BASE_RATE','model_ladder':ladder},'NO_MODEL_PASSED_BASE_RATE'
    features=selected['features']; wf=selected['result']; usable,X,y=_matrix(rows,features); vals=[current_features.get(f) for f in features]
    if any(v is None or not np.isfinite(v) for v in vals): return None,{**wf,'model_ladder':ladder},'CURRENT_FEATURE_COVERAGE_INSUFFICIENT'
    from sklearn.linear_model import LogisticRegression
    from sklearn.isotonic import IsotonicRegression
    from sklearn.preprocessing import StandardScaler
    cal_n=max(30,int(len(y)*.2)); fit_end=len(y)-cal_n
    if fit_end<50 or len(np.unique(y[:fit_end]))<2 or len(np.unique(y[fit_end:]))<2: return None,{**wf,'model_ladder':ladder},'CALIBRATION_SPLIT_INVALID'
    scaler=StandardScaler().fit(X[:fit_end]); model=LogisticRegression(max_iter=1000,C=.5).fit(scaler.transform(X[:fit_end]),y[:fit_end]); raw_cal=model.predict_proba(scaler.transform(X[fit_end:]))[:,1]; iso=IsotonicRegression(out_of_bounds='clip').fit(raw_cal,y[fit_end:]); raw=model.predict_proba(scaler.transform(np.asarray([vals],dtype=float)))[:,1]
    return float(iso.predict(raw)[0]),{**wf,'selected_model':selected['name'],'model_ladder':ladder},''
