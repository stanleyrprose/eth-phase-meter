#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_evaluator():
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from eth_trend_v3.meta_decision import evaluate_meta_decision

    return evaluate_meta_decision


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Combine ETH Phase Meter monitor state with a TradingAgents decision contract."
    )
    parser.add_argument(
        "--monitor",
        default="eth_reports/latest_monitor.json",
        help="Phase Meter latest_monitor.json path",
    )
    parser.add_argument(
        "--tradingagents",
        required=True,
        help="TradingAgents tradingagents-decision-v1 JSON path",
    )
    parser.add_argument(
        "--output",
        default="eth_reports/meta_decision.json",
        help="output path for eth-meta-decision-v1 JSON",
    )
    parser.add_argument(
        "--max-source-age-hours",
        type=float,
        default=24.0,
        help="fail closed if either source artifact is older than this many hours",
    )
    args = parser.parse_args()

    monitor = json.loads(Path(args.monitor).read_text(encoding="utf-8"))
    tradingagents = json.loads(Path(args.tradingagents).read_text(encoding="utf-8"))
    evaluate_meta_decision = _load_evaluator()
    result = evaluate_meta_decision(
        monitor,
        tradingagents,
        max_source_age_hours=args.max_source_age_hours,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    reasons = ",".join(result["reason_codes"])
    print(
        f"Meta Decision: {result['recommendation']} | "
        f"alignment={result['evidence_alignment']} | reasons={reasons}"
    )
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
