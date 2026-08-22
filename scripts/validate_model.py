import json
from pathlib import Path
from eth_trend_v3.backtest import run

report=run(); horizons=report.get('horizons') or {}
gates={h:bool((r.get('metrics') or {}).get('passes_baseline_gate')) for h,r in horizons.items()}
# Promotion remains a human-reviewed release action. This workflow only decides eligibility.
eligible=bool(gates.get('7d') and gates.get('30d'))
out={'status':'ELIGIBLE_FOR_REVIEW' if eligible else 'NOT_ELIGIBLE','production_model':'forecast-baseline-v1.3','candidate_model':'forecast-logistic-calibrated-v1.3','promotion_allowed':False,'candidate_eligible_for_review':eligible,'horizon_gates':gates,'reason':'Manual PR/review required even after validation gates pass.' if eligible else 'Candidate has not passed required 7D and 30D walk-forward/base-rate gates.'}
Path('eth_reports').mkdir(exist_ok=True); Path('eth_reports/validation_report.json').write_text(json.dumps(out,indent=2),encoding='utf-8'); print(json.dumps(out,indent=2))
