from __future__ import annotations

import json
import os
from pathlib import Path

from eth_trend_v3.dataset import load_pit_records
from eth_trend_v3.sizing_research import run_sizing_research


def main() -> None:
    records = load_pit_records(os.getenv("DATABASE_URL"))
    report = run_sizing_research(records)
    root = Path("eth_reports/sizing-research")
    root.mkdir(parents=True, exist_ok=True)
    path = root / "sizing_research.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(
                f"review_checkpoint_reached={'true' if report['review_checkpoint_reached'] else 'false'}\n"
            )
            handle.write(f"status={report['status']}\n")
            handle.write(f"raw_valid_intervals={report['raw_valid_intervals']}\n")

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
