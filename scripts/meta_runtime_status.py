#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_status(state_dir: Path) -> dict:
    state = _read(state_dir / "state.json")
    meta = _read(state_dir / "meta_decision.json")
    notification = state.get("last_notification") or (
        (meta.get("pipeline") or {}).get("notification") or {}
    )
    research = state.get("last_meta_research_dispatch") or (
        (meta.get("pipeline") or {}).get("meta_action_research") or {}
    )
    ta = ((meta.get("sources") or {}).get("tradingagents") or {})
    return {
        "last_processed_run_id": state.get("last_processed_run_id"),
        "pipeline_status": state.get("last_pipeline_status"),
        "recommendation": meta.get("recommendation"),
        "evidence_alignment": meta.get("evidence_alignment"),
        "tradingagents_decision": ta.get("decision"),
        "generated_at": meta.get("generated_at"),
        "notification_status": notification.get("status"),
        "notification_policy_action": notification.get("policy_action"),
        "notification_change_type": notification.get("change_type"),
        "meta_research_dispatch_status": research.get("status"),
        "meta_research_dispatch_run_id": state.get("last_meta_research_dispatch_run_id"),
        "updated_at": state.get("updated_at"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show non-secret ETH Meta runtime status.")
    parser.add_argument(
        "--state-dir",
        default=str(Path.home() / ".eth-meta-pipeline"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status = build_status(Path(args.state_dir).expanduser().resolve())
    if args.json:
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return 0
    for key, value in status.items():
        print(f"{key}: {value if value is not None else 'UNKNOWN'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
