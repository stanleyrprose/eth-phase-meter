from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .dataset import HORIZONS, feature_row, load_pit_records
from .model_state import current_model_state
from .persistence import load_latest_record
from .runtime_model import frozen_inference
from .shadow_forecast import load_shadow_records, new_shadow_record, persist_shadow, settle_shadow_record, shadow_evidence


def _parse(value):
    text = str(value).replace(" UTC", "+00:00").replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _features_from_monitor(primary: dict) -> dict:
    dims = ((primary.get("market_state") or {}).get("dimensions") or {})
    values = {name: (dims.get(name) or {}).get("score") for name in (
        "trend", "valuation", "capital_flow", "crowding", "structural_supply", "volatility_risk"
    )}
    regime = (primary.get("regime") or {}).get("regime")
    from .dataset import REGIME_CODE
    values["regime_code"] = REGIME_CODE.get(regime)
    values["regime"] = regime
    values["feature_time"] = primary.get("timestamp")
    return values


def _settle_due(records: list[dict], pit_records: list[dict]) -> tuple[list[dict], int]:
    price_rows = [feature_row(record) for record in pit_records]
    price_rows = [row for row in price_rows if row and row.get("timeframe") == "4h"]
    price_rows.sort(key=lambda row: _parse(row["timestamp"]))
    settled_out = []
    count = 0
    for record in records:
        if record.get("settled"):
            settled_out.append(record)
            continue
        target = _parse(record["settlement_time"])
        start = _parse(record["forecast_time"])
        path = [row for row in price_rows if start < _parse(row["timestamp"]) <= target]
        if not path or _parse(path[-1]["timestamp"]) < target:
            settled_out.append(record)
            continue
        entry = record.get("entry_price")
        if not isinstance(entry, (int, float)) or entry <= 0:
            settled_out.append(record)
            continue
        updated = settle_shadow_record(
            record,
            entry_price=float(entry),
            path_prices=[float(row["price"]) for row in path],
            settled_at=path[-1]["timestamp"],
        )
        persist_shadow(updated)
        settled_out.append(updated)
        count += 1
    return settled_out, count


def run_shadow_cycle(output_dir: str = "eth_reports/shadow") -> dict:
    pit_records = load_pit_records(os.getenv("DATABASE_URL"))
    existing = load_shadow_records()
    existing, settled_now = _settle_due(existing, pit_records)
    primary = load_latest_record("monitor_state_4h")
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "created": [],
        "settled_now": settled_now,
        "horizons": {},
        "status": "PASS",
    }
    if not primary:
        report["status"] = "NO_MONITOR_STATE"
    else:
        features = _features_from_monitor(primary)
        for horizon in HORIZONS:
            state = current_model_state(horizon)
            if not state or state.get("status") != "SHADOW":
                report["horizons"][horizon] = {"status": "NO_SHADOW_CANDIDATE"}
                continue
            inference = frozen_inference(
                horizon=horizon, model_state=state, current_features=features,
                pit_records=pit_records, mode="SHADOW",
            )
            if not inference.get("available"):
                report["horizons"][horizon] = {"status": "UNAVAILABLE", "reason": inference.get("reason")}
                continue
            record = new_shadow_record(
                experiment_id=inference["experiment_id"],
                model_version=inference["model_version"],
                artifact_hash=inference["artifact_hash"],
                git_sha=state.get("git_sha") or "UNKNOWN",
                horizon=horizon,
                probability=inference["probability_up"],
                baseline_probability=inference["baseline_probability"],
                market_state=primary.get("market_state") or {},
                regime=(primary.get("regime") or {}).get("regime"),
                data_health=(primary.get("data_health") or {}).get("status", "UNKNOWN"),
                feature_snapshot_id=str(primary.get("pit_snapshot_id") or "monitor_state_4h"),
                settlement_time=inference["settlement_time"],
            )
            record["entry_price"] = primary.get("price")
            record["inference_contract_hash"] = inference["inference_contract_hash"]
            record["dataset_hash"] = inference["dataset_hash"]
            record["config_hash"] = inference["config_hash"]
            record["gate_version"] = inference["gate_version"]
            persist_shadow(record)
            report["created"].append(record["forecast_id"])
            report["horizons"][horizon] = {"status": "SHADOW_RECORDED", "forecast_id": record["forecast_id"]}

    all_records = load_shadow_records()
    for horizon in HORIZONS:
        report["horizons"].setdefault(horizon, {})["evidence"] = shadow_evidence(
            all_records, horizon=horizon, effective_evidence_confirmed=False
        )
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "shadow_cycle_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
