from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from eth_trend_v3.alerts import build_alerts
from eth_trend_v3.collectors import collect
from eth_trend_v3.data_health import assess as assess_data_health
from eth_trend_v3.dataset import load_pit_records
from eth_trend_v3.engine import evaluate
from eth_trend_v3.features import all_factors
from eth_trend_v3.market_state import build_market_state
from eth_trend_v3.persistence import persist_json_record
from eth_trend_v3.production_validation import validate_production_summary
from eth_trend_v3.regime import deterministic
from eth_trend_v3.runner import _forecast_bundle


def run_smoke() -> dict:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    raw = collect("4h")
    result = evaluate("4h", raw, all_factors(raw), ts)
    market_state = build_market_state(raw, result)
    health = assess_data_health(raw, result.coverage)
    regime = deterministic(result)
    history = load_pit_records(os.getenv("DATABASE_URL"))
    forecasts, reliability = _forecast_bundle(history, market_state, health, regime)
    primary = {
        "timestamp": ts,
        "price": result.price,
        "market_state": market_state,
        "data_health": health,
        "regime": regime,
        "forecasts": forecasts,
        "model_reliability": reliability,
        "alerts": [],
    }
    primary["alerts"] = build_alerts(primary, {})
    summary = {"4h": primary}
    validation = validate_production_summary(summary, notification_configured=False)
    persisted = persist_json_record("contract_smoke", {"summary": summary, "validation": validation})
    report = {
        "status": "PASS" if validation.get("ok") and (persisted or not os.getenv("DATABASE_URL")) else "FAIL",
        "external_persisted": persisted,
        "database_configured": bool(os.getenv("DATABASE_URL")),
        "validation": validation,
        "summary": summary,
    }
    root = Path("eth_reports/contracts")
    root.mkdir(parents=True, exist_ok=True)
    (root / "contract_smoke.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run_smoke()
    print(json.dumps(report, indent=2, default=str))
    if report["status"] != "PASS":
        raise SystemExit(1)
