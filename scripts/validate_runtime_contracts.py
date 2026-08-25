from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from eth_trend_v3.external_state import (
    _coinmetrics_community_state,
    _defillama_stablecoin_state,
    _dune_execute,
    _farside_eth_etf_state,
)


def _result(name, *, required, ok, status=None, detail=None):
    return {
        "name": name,
        "required": bool(required),
        "status": status or ("PASS" if ok else "FAIL" if required else "OPTIONAL_DEGRADED"),
        "detail": detail,
    }


def validate_runtime_contracts() -> dict:
    checks = []
    try:
        r = requests.get(
            "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
            params={"currency": "ETH", "kind": "future"}, timeout=20,
        )
        body = r.json() if r.ok else {}
        checks.append(_result("deribit", required=True, ok=bool(r.ok and isinstance(body.get("result"), list)), detail=f"http={r.status_code}"))
    except Exception as exc:
        checks.append(_result("deribit", required=True, ok=False, detail=type(exc).__name__))

    cm = _coinmetrics_community_state()
    cm_ok = bool((cm.get("valuation") or {}).get("mvrv") is not None and (cm.get("capital_flow") or {}).get("exchange_netflow_eth") is not None)
    checks.append(_result("coinmetrics-community", required=True, ok=cm_ok, detail=(cm.get("valuation") or {}).get("_error")))

    llama = _defillama_stablecoin_state().get("capital_flow") or {}
    checks.append(_result("defillama-stablecoin", required=True, ok=llama.get("stablecoin_supply_change_usd") is not None, detail=llama.get("_error")))

    farside = _farside_eth_etf_state().get("capital_flow") or {}
    checks.append(_result("farside-etf", required=False, ok=farside.get("etf_flow_usd") is not None, detail=farside.get("_error") or farside.get("_source")))

    if os.getenv("DUNE_API_KEY"):
        dune = _dune_execute("SELECT 1 AS ok")
        checks.append(_result("dune", required=False, ok=not bool(dune.get("_error")), detail=dune.get("_error") or "query-complete"))
    else:
        checks.append(_result("dune", required=False, ok=True, status="SKIPPED_NOT_CONFIGURED", detail=None))

    if os.getenv("FRED_API_KEY"):
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": "DGS10", "api_key": os.getenv("FRED_API_KEY"), "file_type": "json", "limit": 1, "sort_order": "desc"},
                timeout=20,
            )
            checks.append(_result("fred", required=False, ok=bool(r.ok and (r.json().get("observations") or [])), detail=f"http={r.status_code}"))
        except Exception as exc:
            checks.append(_result("fred", required=False, ok=False, detail=type(exc).__name__))
    else:
        checks.append(_result("fred", required=False, ok=True, status="SKIPPED_NOT_CONFIGURED", detail=None))

    dsn = os.getenv("DATABASE_URL")
    if dsn:
        try:
            import psycopg
            required_tables = {
                "eth_monitor_records", "eth_experiment_registry", "eth_model_transition_log",
                "eth_forecasts", "eth_model_artifacts", "eth_research_gate_versions",
                "eth_holdout_registry", "eth_override_log", "eth_model_control_state", "eth_model_states",
            }
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    tables = {row[0] for row in cur.fetchall()}
            missing = sorted(required_tables - tables)
            checks.append(_result("postgres", required=True, ok=not missing, detail={"missing_tables": missing}))
        except Exception as exc:
            checks.append(_result("postgres", required=True, ok=False, detail=type(exc).__name__))
    else:
        checks.append(_result("postgres", required=False, ok=True, status="SKIPPED_NOT_CONFIGURED", detail=None))

    failed_required = [item["name"] for item in checks if item["required"] and item["status"] != "PASS"]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failed_required else "FAIL",
        "failed_required": failed_required,
        "checks": checks,
    }


def main():
    report = validate_runtime_contracts()
    root = Path("eth_reports/contracts")
    root.mkdir(parents=True, exist_ok=True)
    (root / "runtime_contracts.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
