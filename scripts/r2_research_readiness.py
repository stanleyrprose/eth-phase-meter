from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from eth_trend_v3.r2_readiness import assess_r2_readiness, render_r2_readiness_message
from eth_trend_v3.tactical_outcomes import (
    load_tactical_events,
    load_tactical_outcomes,
    load_tactical_price_records,
)
from scripts.send_system_health import send_message


def _write_report(path: str, report: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Report R2 tactical research operational readiness.")
    parser.add_argument(
        "--report",
        default="eth_reports/r2-readiness/r2_research_readiness.json",
    )
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        report = {
            "operational_status": "BLOCKED",
            "operational_reason": "DATABASE_URL_UNAVAILABLE",
            "research_status": "ACCUMULATING_EVIDENCE",
            "research_only": True,
            "event_count": 0,
            "outcome_count": 0,
            "horizons": {},
            "cohorts": {},
            "integrity": {},
        }
    else:
        try:
            report = assess_r2_readiness(
                load_tactical_events(dsn),
                load_tactical_outcomes(dsn),
                load_tactical_price_records(dsn),
            )
        except Exception as exc:
            report = {
                "operational_status": "BLOCKED",
                "operational_reason": "READINESS_QUERY_FAILED",
                "research_status": "ACCUMULATING_EVIDENCE",
                "research_only": True,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "event_count": 0,
                "outcome_count": 0,
                "horizons": {},
                "cohorts": {},
                "integrity": {},
            }

    if args.send_telegram:
        report["telegram"] = send_message(render_r2_readiness_message(report))

    _write_report(args.report, report)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"operational_status={report.get('operational_status','UNKNOWN')}\n")
            handle.write(f"research_status={report.get('research_status','UNKNOWN')}\n")
            handle.write(f"event_count={int(report.get('event_count') or 0)}\n")
            handle.write(f"outcome_count={int(report.get('outcome_count') or 0)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
