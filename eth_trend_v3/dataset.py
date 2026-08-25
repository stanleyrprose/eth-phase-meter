from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path

HORIZONS={"3d":72,"7d":168,"30d":720}
REGIME_CODE={"Low-Vol Bull":1.0,"High-Vol Bull":2.0,"Low-Vol Sideways":0.0,"High-Vol Sideways":0.5,"Low-Vol Bear":-1.0,"High-Vol Bear":-2.0,"Transition":0.0,"Data Degraded":0.0}

def _parse_time(v):
    if isinstance(v,datetime): return v
    s=str(v).replace(" UTC","+00:00").replace("Z","+00:00")
    try: return datetime.fromisoformat(s)
    except Exception: return datetime.strptime(str(v),"%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)

def load_pit_records(database_url:str|None=None,artifact_dir:str="eth_reports/pit")->list[dict]:
    records=[]
    if database_url:
        try:
            import psycopg
            with psycopg.connect(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT payload FROM eth_monitor_records WHERE record_type='pit_snapshot' ORDER BY created_at")
                    records=[r[0] for r in cur.fetchall()]
        except Exception:
            records=[]
    if not records:
        p=Path(artifact_dir)
        if p.exists():
            for f in sorted(p.glob("*.json")):
                if f.name.endswith('_latest.json'): continue
                try: records.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception: pass
    return records


def _canonical_bucket(stamp, *, timeframe: str = "4h"):
    dt=_parse_time(stamp).astimezone(timezone.utc)
    if timeframe=="4h":
        # Align to the monitor cron (minute 15 every 4h), not to ad-hoc dispatch time.
        from datetime import timedelta
        shifted=dt-timedelta(minutes=15)
        bucket_hour=(shifted.hour//4)*4
        return shifted.replace(hour=bucket_hour,minute=0,second=0,microsecond=0)+timedelta(minutes=15)
    return dt.replace(minute=0,second=0,microsecond=0)


def canonicalize_pit_records(records:list[dict], timeframe:str="4h") -> list[dict]:
    """Return one canonical observation per scheduled research bucket.

    Prefer a real scheduled run; otherwise choose the earliest valid observation in the bucket.
    Retries/manual dispatches therefore cannot manufacture additional research samples.
    """
    buckets={}
    for record in records:
        mv=record.get("metric_value") or {}
        if mv.get("timeframe") != timeframe:
            continue
        stamp=record.get("observed_at") or record.get("event_time")
        if not stamp:
            continue
        key=_canonical_bucket(record.get("schedule_nominal_time") or stamp,timeframe=timeframe)
        event=str(record.get("github_event") or "legacy")
        rank=0 if event=="schedule" else 1
        observed=_parse_time(stamp)
        choice=(rank,observed)
        current=buckets.get(key)
        if current is None or choice < current[0]:
            buckets[key]=(choice,record)
    return [buckets[key][1] for key in sorted(buckets)]

def _numeric(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def feature_row(record:dict)->dict|None:
    mv=record.get("metric_value") or {}; state=record.get("market_state_vector") or {}; dims=state.get("dimensions") or {}; price=mv.get("price")
    if not isinstance(price,(int,float)) or price<=0: return None
    regime_name=(record.get('regime') or {}).get('regime')
    row={"timestamp":record.get("observed_at") or record.get("event_time"),"price":float(price),"coverage":float(record.get("coverage") or 0),"timeframe":mv.get("timeframe"),"regime_code":REGIME_CODE.get(regime_name)}
    for k in ("trend","valuation","capital_flow","crowding","structural_supply","volatility_risk"):
        v=(dims.get(k) or {}).get("score"); row[k]=float(v) if isinstance(v,(int,float)) else None
    for k,v in (record.get("feature_clusters") or {}).items():
        s=(v or {}).get("score"); row[f"cluster_{k}"]=float(s) if isinstance(s,(int,float)) else None

    # Raw PIT candidates are exposed for research only. Their presence here does not add them to any production model.
    raw=record.get("raw_payload") or {}; derivatives=raw.get("derivatives") or {}; options=raw.get("options") or {}; macro=raw.get("macro") or {}
    row.update({
        "funding_rate": _numeric(derivatives.get("funding_rate")),
        "open_interest": _numeric(derivatives.get("OI")),
        "derivatives_source": derivatives.get("_data_source"),
        "put_call_oi_ratio": _numeric(options.get("put_call_oi_ratio")),
        "atm_iv_near": _numeric(options.get("atm_iv_near")),
        "iv_skew_25d_proxy_near": _numeric(options.get("iv_skew_25d_proxy_near")),
        "dxy_return": _numeric(macro.get("dxy_chg")) if macro.get("dxy_src") == "FRED" else None,
        "us10y_change_bps": _numeric(macro.get("us10y_change_bps")),
        "us2y_change_bps": _numeric(macro.get("us2y_change_bps")),
        "real10y_change_bps": _numeric(macro.get("real10y_change_bps")),
        "yield_curve_10y2y_pp": _numeric(macro.get("yield_curve_10y2y_pp")),
        "btc_return_24h_pct": _numeric(macro.get("btc_change_24h")),
        "ethbtc_return_24h_pct": _numeric(macro.get("ethbtc_change")),
    })
    near_iv=_numeric(options.get("atm_iv_near")); next_iv=_numeric(options.get("atm_iv_next"))
    row["iv_term_structure_near_next"] = near_iv-next_iv if near_iv is not None and next_iv is not None else None
    return row


def pit_history_depth(records:list[dict], timeframe:str="4h") -> dict:
    """Observation-depth diagnostic only; never use it as promotion evidence by itself."""
    canonical=canonicalize_pit_records(records,timeframe=timeframe)
    rows=[]
    for record in canonical:
        mv=record.get("metric_value") or {}
        if mv.get("timeframe") != timeframe:
            continue
        stamp=record.get("observed_at") or record.get("event_time")
        if stamp:
            rows.append(_parse_time(stamp))
    rows=sorted(set(rows))
    raw_n=len(rows)
    source_raw_n=sum(1 for r in records if (r.get("metric_value") or {}).get("timeframe")==timeframe)
    if not rows:
        return {"timeframe":timeframe,"raw_n":0,"source_raw_n":source_raw_n,"duplicates_removed":source_raw_n,"first_observed_at":None,"last_observed_at":None,"span_days":0.0,"horizons":{},"kind":"DIAGNOSTIC"}
    span_hours=max(0.0,(rows[-1]-rows[0]).total_seconds()/3600.0)
    per_horizon={}
    bar_hours=4 if timeframe=="4h" else 1
    for horizon,hours in HORIZONS.items():
        horizon_bars=max(1,int(hours/bar_hours))
        span_complete_windows=int(span_hours//hours)
        count_complete_windows=raw_n//horizon_bars
        per_horizon[horizon]={
            "horizon_hours":hours,
            "raw_pit_n":raw_n,
            # Manual/retry runs can create multiple records inside one scheduled 4h interval.
            # Never let record density manufacture observation depth: both record count and elapsed span must support it.
            "conservative_nonoverlap_n":min(count_complete_windows, span_complete_windows),
            "count_complete_windows":count_complete_windows,
            "span_complete_windows":span_complete_windows,
            "effective_evidence_confirmed":False,
            "kind":"DIAGNOSTIC",
        }
    return {
        "timeframe":timeframe,
        "raw_n":raw_n,
        "source_raw_n":source_raw_n,
        "duplicates_removed":max(0,source_raw_n-raw_n),
        "first_observed_at":rows[0].isoformat(),
        "last_observed_at":rows[-1].isoformat(),
        "span_days":span_hours/24.0,
        "horizons":per_horizon,
        "kind":"DIAGNOSTIC",
    }

def build_labeled_rows(records:list[dict],horizon_hours:int,tolerance_hours:int=8,timeframe:str="4h")->list[dict]:
    canonical=canonicalize_pit_records(records,timeframe=timeframe)
    rows=[feature_row(r) for r in canonical]; rows=[r for r in rows if r and r.get("timeframe")==timeframe]; rows.sort(key=lambda r:_parse_time(r["timestamp"])); out=[]
    for i,row in enumerate(rows):
        t0=_parse_time(row["timestamp"]).timestamp(); target=t0+horizon_hours*3600; best=None; best_dt=None
        for j in range(i+1,len(rows)):
            tj=_parse_time(rows[j]["timestamp"]).timestamp()
            if tj<=t0: continue
            d=abs(tj-target)
            if best_dt is None or d<best_dt: best,best_dt=rows[j],d
            if tj>target+tolerance_hours*3600: break
        if best is None or best_dt>tolerance_hours*3600: continue
        r=dict(row); r["future_timestamp"]=best["timestamp"]; r["future_price"]=best["price"]; r["future_return"]=best["price"]/row["price"]-1; r["target_up"]=int(r["future_return"]>0); r["target_up_5pct"]=int(r["future_return"]>=.05); out.append(r)
    return out
