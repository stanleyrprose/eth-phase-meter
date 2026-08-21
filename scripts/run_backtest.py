"""PRD v1.3 backtest workflow entrypoint.

Phase 0/1 foundation only: do not claim calibrated probabilities until enough PIT data
exists. This script currently validates the recorded outcome dataset and exits cleanly.
"""
from pathlib import Path
import csv

path = Path("eth_reports/v3_history.csv")
if not path.exists():
    print("No history dataset yet; nothing to backtest.")
    raise SystemExit(0)
with path.open(newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
print(f"History rows: {len(rows)}")
print("Walk-forward/calibration model remains gated until sufficient PIT observations exist.")
