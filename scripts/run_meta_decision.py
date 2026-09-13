#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eth_trend_v3.meta_decision import evaluate_meta_decision


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
    args = parser.parse_args()

    monitor = json.loads(Path(args.monitor).read_text(encoding="utf-8"))
    tradingagents = json.loads(Path(args.tradingagents).read_text(encoding="utf-8"))
    result = evaluate_meta_decision(monitor, tradingagents)

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
