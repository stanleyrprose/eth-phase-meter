from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path

HORIZONS={"3d":72,"7d":168,"30d":720}

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
                try: records.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception: pass
    return records

def feature_row(record:dict)->dict|None:
    mv=record.get("metric_value") or {}; state=record.get("market_state_vector") or {}; dims=state.get("dimensions") or {}; price=mv.get("price")
    if not isinstance(price,(int,float)) or price<=0: return None
    row={"timestamp":record.get("observed_at") or record.get("event_time"),"price":float(price),"coverage":float(record.get("coverage") or 0),"timeframe":mv.get("timeframe")}
    for k in ("trend","valuation","capital_flow","crowding","structural_supply","volatility_risk"):
        v=(dims.get(k) or {}).get("score"); row[k]=float(v) if isinstance(v,(int,float)) else None
    for k,v in (record.get("feature_clusters") or {}).items():
        s=(v or {}).get("score"); row[f"cluster_{k}"]=float(s) if isinstance(s,(int,float)) else None
    return row

def build_labeled_rows(records:list[dict],horizon_hours:int,tolerance_hours:int=8,timeframe:str="4h")->list[dict]:
    rows=[feature_row(r) for r in records]; rows=[r for r in rows if r and r.get("timeframe")==timeframe]; rows.sort(key=lambda r:_parse_time(r["timestamp"])); out=[]
    for i,row in enumerate(rows):
        target=_parse_time(row["timestamp"]).timestamp()+horizon_hours*3600; best=None; best_dt=None
        for j in range(i+1,len(rows)):
            tj=_parse_time(rows[j]["timestamp"]).timestamp(); d=abs(tj-target)
            if best_dt is None or d<best_dt: best,best_dt=rows[j],d
            if tj>target+tolerance_hours*3600: break
        if best is None or best_dt>tolerance_hours*3600: continue
        r=dict(row); r["future_price"]=best["price"]; r["future_return"]=best["price"]/row["price"]-1; r["target_up"]=int(r["future_return"]>0); r["target_up_5pct"]=int(r["future_return"]>=.05); out.append(r)
    return out
