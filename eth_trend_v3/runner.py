from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import eth_phase_meter as core
from .collectors import collect
from .features import all_factors
from .engine import evaluate
from .notify import telegram_text, prd_summary
from .storage import update_history
from .pit import build_pit_record, write_pit_snapshot, write_run_manifest
from .persistence import persist_json_record, persistence_mode, load_latest_record
from .feature_cluster import cluster_factors
from .feature_metadata import enrich_factor_metadata
from .market_state import build_market_state
from .data_health import assess as assess_data_health
from .dataset import HORIZONS, REGIME_CODE, load_pit_records, build_labeled_rows, feature_row
from .forecast import fit_live_probability
from .calibration import reliability_from_metrics, probability_state
from .regime import deterministic
from .hmm_production import infer_live_regime
from .drift import detect_feature_drift, assess_model_health
from .anomaly import detect as detect_anomalies
from .alerts import build_alerts
from .dashboard import write_dashboard
from .promotion import current_production_approval, publication_gate

OUTPUT = Path(core.OUTPUT_DIR)


def _current_features(market_state, regime=None):
    dims = (market_state or {}).get("dimensions") or {}
    out = {
        k: (dims.get(k) or {}).get("score")
        for k in (
            "trend",
            "valuation",
            "capital_flow",
            "crowding",
            "structural_supply",
            "volatility_risk",
        )
    }
    if regime:
        out["regime_code"] = REGIME_CODE.get(regime.get("regime"))
    return out


def _forecast_bundle(records, market_state, health, regime):
    current = _current_features(market_state, regime)
    out = {}
    reliabilities = []
    for horizon, hours in HORIZONS.items():
        rows = build_labeled_rows(records, hours, timeframe="4h")
        prob, wf, reason = fit_live_probability(rows, current)
        metrics = wf.get("metrics") or {}
        rel = reliability_from_metrics(metrics, float(health.get("coverage", 0)), int(wf.get("sample_size", 0)))
        if health.get("status") == "DATA_INSUFFICIENT":
            prob = None
            reason = "DATA_INSUFFICIENT"
        if health.get("stale_sources"):
            prob = None
            reason = "STALE_DATA"
        legacy_forecast = {
            "probability_up": prob,
            "state": probability_state(prob),
            "status": "CALIBRATED" if prob is not None else "UNAVAILABLE",
            "reliability": rel,
            "sample_size": wf.get("sample_size", 0),
            "metrics": metrics,
            "selected_model": wf.get("selected_model"),
            "reason": reason,
            # The legacy on-the-fly fitting path deliberately has no immutable
            # model_version/artifact_hash. publication_gate therefore keeps it
            # UNAVAILABLE even if an unrelated production approval exists.
            "model_version": None,
            "artifact_hash": None,
            "research_only_probability": prob,
        }
        approval = current_production_approval(horizon)
        gated = publication_gate(legacy_forecast, approval)
        if gated.get("probability_up") is not None:
            reliabilities.append(gated.get("reliability"))
        out[horizon] = gated
    overall = (
        "High" if reliabilities and all(x == "High" for x in reliabilities)
        else "Medium" if reliabilities and any(x in ("High", "Medium") for x in reliabilities)
        else "Low"
    )
    return out, overall


def _anomaly_history(records):
    history = {"oi_change_window": [], "liquidation_total": []}
    for record in records[-180:]:
        raw = record.get("raw_payload") or {}
        deriv = raw.get("derivatives") or {}
        for key in history:
            value = deriv.get(key)
            if isinstance(value, (int, float)):
                history[key].append(float(value))
    return history


def _fail_closed_unreliable_forecasts(forecasts, model_health):
    if model_health.get("status") != "MODEL_UNRELIABLE":
        return forecasts
    for forecast in forecasts.values():
        forecast["probability_up"] = None
        forecast["state"] = "UNAVAILABLE"
        forecast["status"] = "UNAVAILABLE"
        forecast["reliability"] = "Low"
        forecast["reason"] = "MODEL_UNRELIABLE"
    return forecasts


def run_one(timeframe, history_records):
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    raw = collect(timeframe)
    factors = all_factors(raw)
    result = evaluate(timeframe, raw, factors, ts)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    update_history(OUTPUT / "v3_history.csv", result)

    clusters = cluster_factors(factors)
    factor_metadata = enrich_factor_metadata(factors)
    market_state = build_market_state(raw, result)
    health = assess_data_health(raw, result.coverage)

    if timeframe == "4h":
        hmm = infer_live_regime(raw)
    else:
        hmm = {"available": False, "reason": "PRIMARY_REGIME_USES_4H"}
    regime = hmm if hmm.get("available") else deterministic(result)
    if not hmm.get("available") and timeframe == "4h":
        regime["fallback_reason"] = hmm.get("reason")

    if timeframe == "4h":
        forecasts, model_reliability = _forecast_bundle(history_records, market_state, health, regime)
    else:
        forecasts = {
            h: {"probability_up": None, "status": "UNAVAILABLE", "reliability": "Low", "reason": "PRIMARY_FORECAST_USES_4H"}
            for h in HORIZONS
        }
        model_reliability = "Low"

    current_row = _current_features(market_state, regime)
    historical_rows = [feature_row(r) for r in history_records]
    historical_rows = [r for r in historical_rows if r]
    feature_drift = detect_feature_drift(historical_rows, current_row)
    model_health = assess_model_health(feature_drift, forecasts, regime)
    forecasts = _fail_closed_unreliable_forecasts(forecasts, model_health)
    if model_health.get("status") == "MODEL_UNRELIABLE":
        model_reliability = "Low"

    anomalies = detect_anomalies(raw, _anomaly_history(history_records))

    payload = {
        "timestamp": ts,
        "timeframe": timeframe,
        "price": result.price,
        "rule_direction": result.final_direction,
        "coverage": result.coverage,
        "market_state": market_state,
        "feature_clusters": clusters,
        "feature_metadata": factor_metadata,
        "data_health": health,
        "regime": regime,
        "forecasts": forecasts,
        "model_reliability": model_reliability,
        "crowding": result.crowding,
        "volatility_risk": result.volatility,
        "model_drift": feature_drift,
        "model_health": model_health,
        "anomalies": anomalies,
    }

    previous = load_latest_record(f"monitor_state_{timeframe}") or {}
    payload["alerts"] = build_alerts(payload, previous, anomalies=anomalies)
    if model_health.get("status") != "NORMAL":
        payload["alerts"].append({"level": 3, "type": model_health.get("status"), "message": json.dumps(model_health, ensure_ascii=False, default=str)})

    record = build_pit_record(
        timeframe, raw, result, market_state=market_state, clusters=clusters, feature_metadata=factor_metadata,
        data_health=health, regime=regime, forecasts=forecasts,
        drift={"feature_drift": feature_drift, "model_health": model_health}, anomalies=anomalies, alerts=payload["alerts"],
    )
    persisted = persist_json_record("pit_snapshot", record)
    record["quality_flags"]["external_persisted"] = persisted
    write_pit_snapshot(OUTPUT, timeframe, record)

    persist_json_record(f"monitor_state_{timeframe}", payload)
    (OUTPUT / f"v3_snapshot_{timeframe}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(telegram_text(result))
    print(f"PIT persistence: {persistence_mode()} | external_persisted={persisted}")
    if timeframe == "4h":
        payload["notification"] = core.send_tg_message(prd_summary(payload))
        persist_json_record(f"monitor_state_{timeframe}", payload)
        (OUTPUT / f"v3_snapshot_{timeframe}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result, payload


def apply_execution_gate(results):
    r1, r4 = results.get("1h"), results.get("4h")
    if not r1 or not r4:
        return
    d1, d4 = r1.final_direction, r4.final_direction
    if abs(d1) >= 20 and abs(d4) >= 20 and d1 * d4 < 0:
        r1.execution_gate = "BLOCKED"
        r1.execution_reason = f"1h与4h方向冲突 (1h={d1:+d}, 4h={d4:+d})"
    elif abs(d1) >= 20 and abs(d4) < 20:
        r1.execution_gate = "WAIT"
        r1.execution_reason = f"4h方向证据不足 ({d4:+d})"
    else:
        r1.execution_gate = "PASS"
        r1.execution_reason = f"4h={d4:+d}"


def main():
    history = load_pit_records(os.getenv("DATABASE_URL"))
    r4, p4 = run_one("4h", history)
    r1, p1 = run_one("1h", history)
    results = {"4h": r4, "1h": r1}
    apply_execution_gate(results)

    summary = {"4h": p4, "1h": p1}
    (OUTPUT / "latest_monitor.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_dashboard(OUTPUT, p4)

    manifest_path = write_run_manifest(
        OUTPUT, results,
        extra={
            "data_health": {"4h": p4["data_health"]["status"], "1h": p1["data_health"]["status"]},
            "forecast_status": {h: v["status"] for h, v in p4["forecasts"].items()},
            "model_reliability": p4["model_reliability"],
            "model_health": p4["model_health"]["status"],
            "regime_engine": p4["regime"].get("engine"),
        },
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["external_persisted"] = persist_json_record("run_manifest", manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    gate = f"🚦 Execution Gate: <b>{r1.execution_gate}</b> | {r1.execution_reason}"
    print(gate)
    gate_notification = core.send_tg_message(gate)
    p4["execution_gate_notification"] = gate_notification
    persist_json_record("monitor_state_4h", p4)
    (OUTPUT / "v3_snapshot_4h.json").write_text(json.dumps(p4, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary["notification"] = {
        "forecast_summary": p4.get("notification"),
        "execution_gate": gate_notification,
    }
    (OUTPUT / "latest_monitor.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


if __name__ == "__main__":
    main()
