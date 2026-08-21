from __future__ import annotations
import csv,json,os
from pathlib import Path
from .dataset import HORIZONS,load_pit_records,build_labeled_rows
from .forecast import expanding_walk_forward
from .ablation import run_ablation
from .correlation import correlation_report

def run(output_dir='eth_reports/model_lab'):
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    records=load_pit_records(os.getenv('DATABASE_URL')); report={'record_count':len(records),'horizons':{}}
    cal_rows=[]; abl_rows=[]
    for h,hours in HORIZONS.items():
        rows=build_labeled_rows(records,hours); wf=expanding_walk_forward(rows); report['horizons'][h]=wf
        for b in (wf.get('metrics') or {}).get('calibration',[]): cal_rows.append({'horizon':h,**b})
        for a in run_ablation(rows): abl_rows.append({'horizon':h,**a})
    four_h_rows=build_labeled_rows(records,HORIZONS['3d'])
    report['correlation']=correlation_report(four_h_rows,['trend','valuation','capital_flow','crowding','structural_supply','volatility_risk'])
    (out/'metrics.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    if cal_rows:
        with (out/'calibration.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=cal_rows[0].keys()); w.writeheader(); w.writerows(cal_rows)
    if abl_rows:
        fields=['horizon','model','features','available','sample_size','brier','log_loss','brier_lift_vs_base','incremental_brier']
        with (out/'ablation.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
            for r in abl_rows:
                rr=dict(r); rr['features']='|'.join(rr['features']); w.writerow(rr)
    lines=['# Model Validation Report','',f"PIT records: {len(records)}",'']
    for h,r in report['horizons'].items():
        lines += [f'## {h}',f"- available: {r.get('available',False)}",f"- sample_size: {r.get('sample_size',0)}",f"- reason: {r.get('reason','')}",f"- metrics: `{json.dumps(r.get('metrics',{}),ensure_ascii=False)}`",'']
    lines += ['## Feature correlation',f"`{json.dumps(report['correlation'],ensure_ascii=False)}`",'']
    (out/'validation_report.md').write_text('\n'.join(lines),encoding='utf-8')
    return report
