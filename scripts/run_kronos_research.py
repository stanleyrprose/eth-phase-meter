#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_components():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import github_actions_runner as market
    from eth_trend_v3.kronos_research import (
        append_kronos_pit,
        build_kronos_pit_record,
        evaluate_kronos_pit,
        load_kronos_pit,
        resolve_kronos_outcomes,
    )

    return (
        market,
        append_kronos_pit,
        build_kronos_pit_record,
        evaluate_kronos_pit,
        load_kronos_pit,
        resolve_kronos_outcomes,
    )


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed, resolve, and evaluate Kronos PIT shadow research.")
    parser.add_argument("--state-dir", default=str(Path.home() / ".eth-meta-pipeline"))
    args = parser.parse_args(argv)
    (
        market,
        append_kronos_pit,
        build_kronos_pit_record,
        evaluate_kronos_pit,
        load_kronos_pit,
        resolve_kronos_outcomes,
    ) = _load_components()

    state_dir = Path(args.state_dir).expanduser().resolve()
    monitor = _read_json(state_dir / "latest_monitor.json")
    decision = _read_json(state_dir / "tradingagents_decision.json")
    kronos = _read_json(state_dir / "kronos_evidence.json")
    meta = _read_json(state_dir / "meta_decision.json")
    state = _read_json(state_dir / "state.json")
    if not monitor or not kronos or not meta:
        raise RuntimeError("KRONOS_RESEARCH_STATE_INCOMPLETE")

    pipeline = meta.get("pipeline") or {}
    run_id = pipeline.get("monitor_run_id") or state.get("last_processed_run_id") or "manual"
    run_sha = pipeline.get("monitor_git_sha") or state.get("last_monitor_git_sha")
    pit_path = state_dir / "kronos_pit.jsonl"
    report_path = state_dir / "kronos_research_report.json"

    record = build_kronos_pit_record(
        monitor=monitor,
        tradingagents=decision,
        kronos=kronos,
        meta=meta,
        monitor_run_id=run_id,
        monitor_git_sha=run_sha,
    )
    appended = append_kronos_pit(pit_path, record)

    candles_by_timeframe = {}
    for timeframe in ("1h", "4h"):
        candles = market.fetch_market_klines(interval=timeframe, limit=220)
        if candles is not None and len(candles) >= 2:
            candles_by_timeframe[timeframe] = candles
    resolved = resolve_kronos_outcomes(
        pit_path,
        candles_by_timeframe=candles_by_timeframe,
    )
    records = load_kronos_pit(pit_path)
    report = evaluate_kronos_pit(records)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "pit_records": len(records),
                "appended": appended,
                "resolved_outcomes": resolved,
                "report": report,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
