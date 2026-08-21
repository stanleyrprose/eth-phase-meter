"""Candidate-vs-production validation gate placeholder required by PRD v1.3."""
import json
from pathlib import Path

report = {
    "status": "NOT_ENOUGH_CALIBRATED_DATA",
    "production_model": "baseline-rule-v3.1",
    "candidate_model": None,
    "promotion_allowed": False,
    "reason": "Probability forecast model has not yet passed walk-forward/calibration gates.",
}
Path("eth_reports").mkdir(exist_ok=True)
Path("eth_reports/validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
