from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import eth_phase_meter as core
from .collectors import collect
from .features import all_factors
from .engine import evaluate
from .notify import telegram_text, prd_summary, tactical_summary
from .storage import update_history
from .pit import build_pit_record, write_pit_snapshot, write_run_manifest
from .persistence import persist_json_record, persistence_mode, load_latest_record
from .feature_cluster import cluster_factors
from .feature_metadata import enrich_factor_metadata
from .market_state import build_market_state
from .data_health import assess as assess_data_health
from .dataset import HORIZONS, REGIME_CODE, load_pit_records, build_labeled_rows, feature_row, canonicalize_pit_records
from .forecast import fit_live_probability
from .calibration import reliability_from_metrics, probability_state
from .regime import deterministic
from .hmm_production import infer_live_regime
from .drift import detect_feature_drift, assess_model_health
from .anomaly import detect as detect_anomalies
from .alerts import build_alerts
from .dashboard import write_dashboard
from .promotion import current_production_approval, publication_gate
from .model_state import current_model_state
from .runtime_model import frozen_inference
from .production_control import evaluate_runtime_demotion
from .shadow_forecast import new_shadow_record, persist_shadow
from .structural_flow import enrich_staking_netflow

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
        out["regime"] = regime.get("regime")
    return out


def _forecast_bundle(records, market_state, health, regime):
    current = _current_features(market_state, regime)
    out = {}
    reliabilities = []
    for horizon, hours in HORIZONS.items():
        # Automatic production demotion is evaluated before any publication attempt.
        evaluate_runtime_demotion(horizon, data_health=str(health.get("status") or "UNKNOWN"))
        state = current_model_state(horizon)
        if state and state.get("status") == "PRODUCTION":
            frozen = frozen_inference(
                horizon=horizon,
                model_state=state,
                current_features=current,
                pit_records=records,
                mode="PRODUCTION",
            )
            if frozen.get("available"):
                production_forecast = {
                    **frozen,
                    "reason": "",
                    "metrics": state.get("evidence") or {},
                    "selected_model": state.get("model_id"),
                    "research_only_probability": None,
                }
            else:
                production_forecast = {
                    "probability_up": None,
                    "state": "UNAVAILABLE",
                    "status": "UNAVAILABLE",
                    "reliability": "UNAVAILABLE",
                    "reason": frozen.get("reason") or "MODEL_ARTIFACT_MISSING",
                    "model_version": state.get("model_version"),
                    "artifact_hash": state.get("artifact_hash"),
                    "inference_contract_hash": state.get("inference_contract_hash"),
                    "metrics": state.get("evidence") or {},
                    "selected_model": state.get("model_id"),
                    "research_only_probability": None,
                }
            gated = publication_gate(production_forecast, state, horizon=horizon)
            if gated.get("probability_up") is not None:
                reliabilities.append(gated.get("reliability"))
            out[horizon] = gated
            continue

        # Legacy on-the-fly path remains research-only and can never satisfy immutable
        # production artifact/version requirements.
        rows = build_labeled_rows(records, hours, timeframe="4h")
        prob, wf, reason = fit_live_probability(rows, current)
        metrics = wf.get("metrics") or {}
        rel = reliability_from_metrics(metrics, float(health.get("coverage", 0)), int(wf.get("sample_size", 0)))
        if health.get("status") == "DATA_INSUFFICIENT":
            prob = None
            reason = "INSUFFICIENT_DATA"
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
            "model_version": None,
            "artifact_hash": None,
            "inference_contract_hash": None,
            "research_only_probability": prob,
        }
        approval = current_production_approval(horizon)
        gated = publication_gate(legacy_forecast, approval, horizon=horizon)
        if gated.get("probability_up") is not None:
            reliabilities.append(gated.get("reliability"))
        out[horizon] = gated
    overall = (
        "High" if reliabilities and all(x == "HIGH" for x in reliabilities)
        else "Medium" if reliabilities and any(x in ("HIGH", "MEDIUM", "High", "Medium") for x in reliabilities)
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


def _persist_production_forecasts(payload: dict, *, pit_snapshot_id: str) -> list[str]:
    created = []
    for horizon, forecast in (payload.get("forecasts") or {}).items():
        if forecast.get("status") != "PRODUCTION" or forecast.get("probability_up") is None:
            continue
        record = new_shadow_record(
            experiment_id=forecast.get("experiment_id") or (forecast.get("production_approval") or {}).get("experiment_id") or "UNKNOWN",
            model_version=forecast.get("model_version"),
            artifact_hash=forecast.get("artifact_hash"),
            git_sha=os.getenv("GITHUB_SHA", "unknown"),
            horizon=horizon,
            probability=float(forecast["probability_up"]),
            baseline_probability=float(forecast["baseline_probability"]),
            market_state=payload.get("market_state") or {},
            regime=(payload.get("regime") or {}).get("regime"),
            data_health=(payload.get("data_health") or {}).get("status", "UNKNOWN"),
            feature_snapshot_id=pit_snapshot_id,
            settlement_time=forecast.get("settlement_time"),
        )
        record["mode"] = "PRODUCTION"
        record["entry_price"] = payload.get("price")
        record["inference_contract_hash"] = forecast.get("inference_contract_hash")
        record["dataset_hash"] = forecast.get("dataset_hash")
        record["config_hash"] = forecast.get("config_hash")
        record["gate_version"] = forecast.get("gate_version")
        persist_shadow(record)
        created.append(record["forecast_id"])
    return created


def run_one(timeframe, history_records):
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    raw = collect(timeframe)
    if timeframe == "4h":
        raw = enrich_staking_netflow(raw, history_records)
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
    drift_records = canonicalize_pit_records(history_records, timeframe=timeframe)
    historical_rows = [feature_row(r) for r in drift_records]
    historical_rows = [r for r in historical_rows if r]
    feature_drift = detect_feature_drift(
        historical_rows,
        current_row,
        current_versions=market_state.get("dimension_versions") or {},
    )
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
        "available_bias": result.available_bias,
        "tactical_state": result.state,
        "rule_regime": result.regime,
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
    pit_path = write_pit_snapshot(OUTPUT, timeframe, record)
    if timeframe == "4h":
        payload["production_forecast_ids"] = _persist_production_forecasts(payload, pit_snapshot_id=pit_path.name)

    persist_json_record(f"monitor_state_{timeframe}", payload)
    (OUTPUT / f"v3_snapshot_{timeframe}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(telegram_text(result))
    print(f"PIT persistence: {persistence_mode()} | external_persisted={persisted}")
    if timeframe == "4h":
        payload["notification"] = core.send_tg_message(prd_summary(payload))
        persist_json_record(f"monitor_state_{timeframe}", payload)
        (OUTPUT / f"v3_snapshot_{timeframe}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result, payload


def apply_4h_confirmation(result_1h, direction_4h: int):
    d1, d4 = result_1h.final_direction, int(direction_4h)
    if abs(d1) >= 20 and abs(d4) >= 20 and d1 * d4 < 0:
        result_1h.execution_gate = "BLOCKED"
        result_1h.execution_reason = f"1h与4h方向冲突 (1h={d1:+d}, 4h={d4:+d})"
    elif abs(d1) >= 20 and abs(d4) < 20:
        result_1h.execution_gate = "WAIT"
        result_1h.execution_reason = f"4h方向证据不足 ({d4:+d})"
    else:
        result_1h.execution_gate = "PASS"
        result_1h.execution_reason = f"4h={d4:+d}"
    return result_1h


def apply_execution_gate(results):
    r1, r4 = results.get("1h"), results.get("4h")
    if not r1 or not r4:
        return
    apply_4h_confirmation(r1, r4.final_direction)


def _send_tactical_1h(result, payload_1h, triggers=None):
    message = tactical_summary(result)
    if triggers:
        message += "\n🔔 Trigger: " + "; ".join(triggers)
    print(message)
    notification = core.send_tg_message(message)
    payload_1h["notification"] = notification
    return notification


def _process_tactical_1h(result, payload_1h, primary_4h, previous_1h):
    if primary_4h.get("rule_direction") is None:
        result.execution_gate = "WAIT"
        result.execution_reason = "缺少最新4H状态"
        decision = {"status": "SKIPPED", "reason": "NO_4H_STATE", "triggers": []}
    else:
        apply_4h_confirmation(result, int(primary_4h["rule_direction"]))
        if not previous_1h:
            decision = {"status": "SKIPPED", "reason": "BASELINE_ESTABLISHED", "triggers": []}
        else:
            from .tactical_alerts import notification_reasons

            triggers = notification_reasons(result, previous_1h)
            if triggers:
                notification = _send_tactical_1h(result, payload_1h, triggers=triggers)
                decision = {**notification, "reason": "SIGNIFICANT_CHANGE", "triggers": triggers}
            else:
                decision = {"status": "SKIPPED", "reason": "NO_SIGNIFICANT_CHANGE", "triggers": []}

    payload_1h["execution_gate"] = result.execution_gate
    payload_1h["execution_reason"] = result.execution_reason
    payload_1h["available_bias"] = result.available_bias
    payload_1h["tactical_state"] = result.state
    payload_1h["rule_regime"] = result.regime
    payload_1h["notification_decision"] = decision
    return decision


def main():
    history = load_pit_records(os.getenv("DATABASE_URL"))
    previous_1h = load_latest_record("monitor_state_1h") or {}
    r4, p4 = run_one("4h", history)
    r1, p1 = run_one("1h", history)
    tactical_decision = _process_tactical_1h(r1, p1, p4, previous_1h)

    persist_json_record("monitor_state_1h", p1)
    (OUTPUT / "v3_snapshot_1h.json").write_text(
        json.dumps(p1, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    summary = {"4h": p4, "1h": p1}
    (OUTPUT / "latest_monitor.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_dashboard(OUTPUT, p4)

    manifest_path = write_run_manifest(
        OUTPUT, {"4h": r4, "1h": r1},
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

    summary["notification"] = {
        "forecast_summary": p4.get("notification"),
        "tactical_1h": tactical_decision,
    }
    (OUTPUT / "latest_monitor.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if tactical_decision.get("reason") == "SIGNIFICANT_CHANGE" and tactical_decision.get("status") != "SENT":
        raise SystemExit(1)
    return summary


if __name__ == "__main__":
    main()
