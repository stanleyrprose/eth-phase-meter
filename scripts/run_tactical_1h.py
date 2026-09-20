from __future__ import annotations

import json
import os
from pathlib import Path

import eth_phase_meter as core
from eth_trend_v3.dataset import load_pit_records
from eth_trend_v3.persistence import load_latest_record, persist_json_record
from eth_trend_v3.runner import _process_tactical_1h, run_one


OUTPUT = Path(core.OUTPUT_DIR)


def main():
    previous = load_latest_record("monitor_state_1h") or {}
    primary_4h = load_latest_record("monitor_state_4h") or {}
    history = load_pit_records(os.getenv("DATABASE_URL"))

    result, payload = run_one("1h", history)
    decision = _process_tactical_1h(result, payload, primary_4h, previous)

    persist_json_record("monitor_state_1h", payload)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "v3_snapshot_1h.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (OUTPUT / "latest_tactical_1h.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(decision, ensure_ascii=False, default=str))

    if decision.get("reason") == "SIGNIFICANT_CHANGE" and decision.get("status") != "SENT":
        raise SystemExit(1)
    return payload


if __name__ == "__main__":
    main()
