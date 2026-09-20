from __future__ import annotations

import json
import os
from pathlib import Path

from eth_trend_v3.dataset import load_pit_records
from eth_trend_v3.promotion import current_production_approval
from eth_trend_v3.research_gates import HORIZONS, build_research_gate_snapshot


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"required research gate input missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    readiness = _read_json(Path("eth_reports/research-readiness/research_readiness.json"))
    sizing = _read_json(Path("eth_reports/sizing-research/sizing_research.json"))
    records = load_pit_records(os.getenv("DATABASE_URL"))
    approvals = {horizon: current_production_approval(horizon) for horizon in HORIZONS}

    report = build_research_gate_snapshot(
        readiness,
        sizing,
        records,
        approvals,
    )

    root = Path("eth_reports/research-gates")
    root.mkdir(parents=True, exist_ok=True)
    path = root / "research-gates.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"status={report['decision']['status']}\n")
            handle.write(
                f"actionable={'true' if report['decision']['actionable'] else 'false'}\n"
            )

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
