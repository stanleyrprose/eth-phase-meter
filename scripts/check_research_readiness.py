from __future__ import annotations

import json
import os
from pathlib import Path

from eth_trend_v3.dataset import load_pit_records
from eth_trend_v3.research_readiness import assess_research_readiness


def main():
    report=assess_research_readiness(load_pit_records(os.getenv("DATABASE_URL")))
    root=Path("eth_reports/research-readiness")
    root.mkdir(parents=True,exist_ok=True)
    (root/"research_readiness.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    output=os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output,"a",encoding="utf-8") as fh:
            fh.write(f"run_research_benchmark={'true' if report['run_research_benchmark'] else 'false'}\n")
            fh.write(f"status={report['status']}\n")
    print(json.dumps(report,indent=2,default=str))


if __name__=="__main__":
    main()
