from __future__ import annotations

import json
import os
from pathlib import Path

import eth_phase_meter as core
from eth_trend_v3.dataset import load_pit_records
from eth_trend_v3.persistence import load_latest_record, persist_json_record
from eth_trend_v3.runner import _send_tactical_1h, apply_4h_confirmation, run_one
from eth_trend_v3.tactical_alerts import notification_reasons


OUTPUT = Path(core.OUTPUT_DIR)


def main():
    previous = load_latest_record("monitor_state_1h") or {}
    primary_4h = load_latest_record("monitor_state_4h") or {}
    history = load_pit_records(os.getenv("DATABASE_URL"))

    result, payload = run_one("1h", history)

    if primary_4h.get("rule_direction") is None:
        result.execution_gate = "WAIT"
        result.execution_reason = "缺少最新4H状态"
        decision = {"status": "SKIPPED", "reason": "NO_4H_STATE", "triggers": []}
    else:
        apply_4h_confirmation(result, int(primary_4h["rule_direction"]))
        if not previous:
            decision = {"status": "SKIPPED", "reason": "BASELINE_ESTABLISHED", "triggers": []}
        else:
            triggers = notification_reasons(result, previous)
            if triggers:
                notification = _send_tactical_1h(result, payload, triggers=triggers)
                decision = {**notification, "reason": "SIGNIFICANT_CHANGE", "triggers": triggers}
            else:
                decision = {"status": "SKIPPED", "reason": "NO_SIGNIFICANT_CHANGE", "triggers": []}

    payload["execution_gate"] = result.execution_gate
    payload["execution_reason"] = result.execution_reason
    payload["available_bias"] = result.available_bias
    payload["tactical_state"] = result.state
    payload["rule_regime"] = result.regime
    payload["notification_decision"] = decision

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
