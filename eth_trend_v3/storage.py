from __future__ import annotations
import csv
from datetime import datetime, timezone
from pathlib import Path
FIELDS=['timestamp','timeframe','price','direction','available_bias','coverage','crowding','volatility','regime','state','future_4h_return','future_24h_return']
def _parse(ts): return datetime.strptime(ts,'%Y-%m-%d %H:%M UTC').replace(tzinfo=timezone.utc)
def update_history(path:Path,result)->None:
    path.parent.mkdir(parents=True,exist_ok=True); rows=[]
    if path.exists():
        with path.open(newline='',encoding='utf-8') as f: rows=list(csv.DictReader(f))
    now=_parse(result.timestamp); current=float(result.price)
    for row in rows:
        if row.get('timeframe')!=result.timeframe: continue
        age=(now-_parse(row['timestamp'])).total_seconds()/3600; old=float(row['price']) if row.get('price') else 0
        if old<=0: continue
        if not row.get('future_4h_return') and 3.5<=age<=8.5: row['future_4h_return']=f'{(current/old-1)*100:.6f}'
        if not row.get('future_24h_return') and 23.5<=age<=28.5: row['future_24h_return']=f'{(current/old-1)*100:.6f}'
    rows.append({'timestamp':result.timestamp,'timeframe':result.timeframe,'price':f'{result.price:.8f}','direction':result.final_direction,'available_bias':result.available_bias,'coverage':result.coverage,'crowding':result.crowding,'volatility':result.volatility,'regime':result.regime,'state':result.state,'future_4h_return':'','future_24h_return':''})
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(rows[-5000:])
