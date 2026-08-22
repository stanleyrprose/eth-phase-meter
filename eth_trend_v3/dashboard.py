from __future__ import annotations
import html,json
from pathlib import Path

def _shell(title,body):
    return f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>body{{font-family:system-ui;max-width:1100px;margin:40px auto;padding:0 20px}}nav a{{margin-right:16px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px;text-align:left}}pre{{background:#f6f8fa;padding:16px;overflow:auto}}</style><nav><a href='overview.html'>Overview</a><a href='state-explorer.html'>State Explorer</a><a href='model-lab.html'>Model Lab</a><a href='data-health.html'>Data Health</a></nav><h1>{html.escape(title)}</h1>{body}<p><small>Research observation only. Not investment advice.</small></p>"

def write_dashboard(output:Path,payload:dict)->Path:
    d=output/'dashboard'; d.mkdir(parents=True,exist_ok=True)
    forecasts=payload.get('forecasts') or {}; dims=(payload.get('market_state') or {}).get('dimensions') or {}
    frows=''.join(f"<tr><td>{h}</td><td>{('%.1f%%'%(100*v['probability_up'])) if isinstance(v.get('probability_up'),(int,float)) else 'Unavailable'}</td><td>{v.get('reliability','Low')}</td><td>{v.get('status','')}</td></tr>" for h,v in forecasts.items())
    overview=f"<p>Price: <b>${payload.get('price',0):,.2f}</b></p><p>Regime: <b>{html.escape(str((payload.get('regime') or {}).get('regime')))}</b> | Model Reliability: <b>{payload.get('model_reliability','Low')}</b></p><table><tr><th>Horizon</th><th>P(Up)</th><th>Reliability</th><th>Status</th></tr>{frows}</table>"
    (d/'overview.html').write_text(_shell('ETH Monitor — Overview',overview),encoding='utf-8')
    rows=''.join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v.get('score')))}</td><td>{v.get('coverage',0):.0f}%</td><td>{html.escape(str(v.get('semantic','')))}</td></tr>" for k,v in dims.items())
    (d/'state-explorer.html').write_text(_shell('State Explorer',f"<table><tr><th>Dimension</th><th>Score</th><th>Coverage</th><th>Meaning</th></tr>{rows}</table>"),encoding='utf-8')
    model_payload={'forecasts':forecasts,'regime':payload.get('regime'),'model_drift':payload.get('model_drift'),'feature_clusters':payload.get('feature_clusters')}
    (d/'model-lab.html').write_text(_shell('Model Lab',f"<pre>{html.escape(json.dumps(model_payload,ensure_ascii=False,indent=2,default=str))}</pre>"),encoding='utf-8')
    (d/'data-health.html').write_text(_shell('Data Health',f"<pre>{html.escape(json.dumps(payload.get('data_health') or {},ensure_ascii=False,indent=2,default=str))}</pre>"),encoding='utf-8')
    index=output/'dashboard.html'; index.write_text(_shell('ETH Market Monitor',"<p>Open the four dashboard pages above.</p>"),encoding='utf-8'); return index
