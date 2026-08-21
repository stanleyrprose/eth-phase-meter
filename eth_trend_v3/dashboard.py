from __future__ import annotations
import html,json
from pathlib import Path

def write_dashboard(output:Path,payload:dict)->Path:
    output.mkdir(parents=True,exist_ok=True); pretty=html.escape(json.dumps(payload,ensure_ascii=False,indent=2,default=str)); forecasts=payload.get("forecasts") or {}; dims=(payload.get("market_state") or {}).get("dimensions") or {}
    rows="".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v.get('score')))}</td><td>{v.get('coverage',0):.0f}%</td></tr>" for k,v in dims.items()); frows="".join(f"<tr><td>{h}</td><td>{('%.1f%%'%(100*v['probability_up'])) if isinstance(v.get('probability_up'),(int,float)) else 'Unavailable'}</td><td>{v.get('reliability','Low')}</td><td>{v.get('status','')}</td></tr>" for h,v in forecasts.items())
    doc=f"<!doctype html><meta charset='utf-8'><title>ETH Monitor</title><style>body{{font-family:system-ui;max-width:1100px;margin:40px auto;padding:0 20px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px}}pre{{background:#f6f8fa;padding:16px;overflow:auto}}</style><h1>ETH Market Monitor</h1><p>Generated from GitHub Actions artifact. Not investment advice.</p><h2>Overview</h2><p>Regime: <b>{html.escape(str(payload.get('regime')))}</b> | Data: <b>{html.escape(str(payload.get('data_health',{}).get('status')))}</b></p><h2>Forecast</h2><table><tr><th>Horizon</th><th>P(Up)</th><th>Reliability</th><th>Status</th></tr>{frows}</table><h2>State Explorer</h2><table><tr><th>Dimension</th><th>Score</th><th>Coverage</th></tr>{rows}</table><h2>Model Lab / Data Health</h2><pre>{pretty}</pre>"
    p=output/"dashboard.html"; p.write_text(doc,encoding="utf-8"); return p
