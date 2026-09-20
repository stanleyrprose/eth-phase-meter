from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

KRONOS_PIT_SCHEMA_VERSION = "kronos-pit-v1"
KRONOS_RESEARCH_REPORT_VERSION = "kronos-research-report-v2-nonoverlap"
KRONOS_PROMOTION_POLICY_VERSION = "kronos-promotion-policy-v1"
PRIMARY_PROMOTION_TIMEFRAME = "4h"
PROMOTION_MIN_EFFECTIVE_N = 100
PROMOTION_MIN_CONFLICT_N = 30
PROMOTION_MIN_DIRECTION_HIT_RATE = 0.55


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace(" UTC", "+00:00").replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sign(value: Any, *, neutral_band: float = 0.0) -> int:
    number = _number(value)
    if number is None or abs(number) <= neutral_band:
        return 0
    return 1 if number > 0 else -1


def evidence_id(kronos: dict[str, Any]) -> str:
    model = kronos.get("model") or {}
    horizons = kronos.get("horizons") or {}
    canonical = {
        "asset": kronos.get("asset"),
        "generated_at": kronos.get("generated_at"),
        "model_name": model.get("name"),
        "model_repo_sha": model.get("repo_sha"),
        "1h_source": (horizons.get("1h") or {}).get("source_last_timestamp"),
        "4h_source": (horizons.get("4h") or {}).get("source_last_timestamp"),
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_kronos_pit_record(
    *,
    monitor: dict[str, Any],
    tradingagents: dict[str, Any],
    kronos: dict[str, Any],
    meta: dict[str, Any],
    monitor_run_id: int | str,
    monitor_git_sha: str | None,
) -> dict[str, Any]:
    model = kronos.get("model") or {}
    record = {
        "schema_version": KRONOS_PIT_SCHEMA_VERSION,
        "evidence_id": evidence_id(kronos),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "monitor_run_id": monitor_run_id,
        "monitor_git_sha": monitor_git_sha,
        "asset": "ETH-USD",
        "kronos_generated_at": kronos.get("generated_at"),
        "kronos_model": model,
        "tradingagents": {
            "decision": tradingagents.get("decision_normalized") or tradingagents.get("decision"),
            "generated_at": tradingagents.get("generated_at"),
        },
        "meta": {
            "recommendation": meta.get("recommendation"),
            "evidence_alignment": meta.get("evidence_alignment"),
            "kronos_alignment": ((meta.get("shadow_evidence") or {}).get("kronos_alignment")),
        },
        "horizons": {},
        "guardrails": {
            "research_only": True,
            "production_decision_active": False,
            "probability_generated": False,
        },
    }

    for timeframe in ("1h", "4h"):
        forecast = (kronos.get("horizons") or {}).get(timeframe) or {}
        phase = monitor.get(timeframe) or {}
        if not forecast:
            continue
        record["horizons"][timeframe] = {
            "source_last_timestamp": forecast.get("source_last_timestamp"),
            "source_last_close": _number(forecast.get("source_last_close")),
            "forecast_end_timestamp": forecast.get("forecast_end_timestamp"),
            "pred_len": int(forecast.get("pred_len") or 0),
            "lookback": int(forecast.get("lookback") or 0),
            "sample_count": int(forecast.get("sample_count") or 0),
            "predicted_terminal_return_pct": _number(forecast.get("median_terminal_return_pct")),
            "predicted_terminal_close": _number(forecast.get("median_terminal_close")),
            "direction_score": _number(forecast.get("direction_score")),
            "sample_directional_agreement_pct": _number(
                forecast.get("sample_directional_agreement_pct")
            ),
            "terminal_return_std_pct": _number(forecast.get("terminal_return_std_pct")),
            "momentum_baseline_return_pct": _number(forecast.get("trailing_momentum_return_pct")),
            "phase_direction": _number(phase.get("rule_direction")),
            "phase_regime": (phase.get("regime") or {}).get("regime"),
            "outcome": None,
        }
    return record


def load_kronos_pit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def append_kronos_pit(path: Path, record: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {row.get("evidence_id") for row in load_kronos_pit(path)}
    if record.get("evidence_id") in existing:
        return False
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
    return True


def _closed_frame(candles: pd.DataFrame) -> pd.DataFrame:
    frame = candles.copy()
    if "open_time" in frame.columns:
        raw = frame["open_time"]
        if getattr(raw.dtype, "kind", "") in {"i", "u", "f"}:
            frame["timestamp"] = pd.to_datetime(raw, unit="ms", utc=True)
        else:
            frame["timestamp"] = pd.to_datetime(raw, utc=True)
    elif "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    else:
        raise ValueError("candles need open_time or timestamp")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)


def resolve_kronos_outcomes(
    path: Path,
    *,
    candles_by_timeframe: dict[str, pd.DataFrame],
    observed_at: datetime | None = None,
) -> int:
    records = load_kronos_pit(path)
    if not records:
        return 0
    now = observed_at or datetime.now(timezone.utc)
    frames = {key: _closed_frame(value) for key, value in candles_by_timeframe.items()}
    resolved = 0

    for record in records:
        for timeframe, horizon in (record.get("horizons") or {}).items():
            if horizon.get("outcome") is not None or timeframe not in frames:
                continue
            target = _parse_time(horizon.get("forecast_end_timestamp"))
            if target is None or target > now:
                continue
            frame = frames[timeframe]
            candidates = frame[frame["timestamp"] >= pd.Timestamp(target)]
            if candidates.empty:
                continue
            bar = candidates.iloc[0]
            actual_timestamp = pd.Timestamp(bar["timestamp"]).to_pydatetime()
            bar_hours = 1 if timeframe == "1h" else 4
            if (actual_timestamp - target).total_seconds() > bar_hours * 3600:
                continue

            source_close = _number(horizon.get("source_last_close"))
            actual_close = _number(bar.get("close"))
            predicted_close = _number(horizon.get("predicted_terminal_close"))
            predicted_return = _number(horizon.get("predicted_terminal_return_pct"))
            momentum_return = _number(horizon.get("momentum_baseline_return_pct"))
            phase_direction = _number(horizon.get("phase_direction"))
            if not source_close or actual_close is None:
                continue

            actual_return = (actual_close / source_close - 1.0) * 100.0
            momentum_close = (
                source_close * (1.0 + momentum_return / 100.0)
                if momentum_return is not None
                else None
            )
            outcome = {
                "resolved_at": now.isoformat(),
                "actual_timestamp": actual_timestamp.astimezone(timezone.utc).isoformat(),
                "actual_close": actual_close,
                "actual_return_pct": actual_return,
                "kronos_direction_hit": (
                    _sign(predicted_return) == _sign(actual_return)
                    if _sign(predicted_return) != 0 and _sign(actual_return) != 0
                    else None
                ),
                "momentum_direction_hit": (
                    _sign(momentum_return) == _sign(actual_return)
                    if _sign(momentum_return) != 0 and _sign(actual_return) != 0
                    else None
                ),
                "phase_direction_hit": (
                    _sign(phase_direction, neutral_band=10.0) == _sign(actual_return)
                    if _sign(phase_direction, neutral_band=10.0) != 0 and _sign(actual_return) != 0
                    else None
                ),
                "kronos_abs_price_error_pct": (
                    abs(predicted_close / actual_close - 1.0) * 100.0
                    if predicted_close is not None
                    else None
                ),
                "persistence_abs_price_error_pct": abs(source_close / actual_close - 1.0) * 100.0,
                "momentum_abs_price_error_pct": (
                    abs(momentum_close / actual_close - 1.0) * 100.0
                    if momentum_close is not None
                    else None
                ),
            }
            horizon["outcome"] = outcome
            resolved += 1

    if resolved:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
                )
        tmp.replace(path)
    return resolved


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _hit_rate(values: list[bool]) -> float | None:
    return float(np.mean([1.0 if value else 0.0 for value in values])) if values else None


def _exact_two_sided_binomial_p(hits: int, n: int) -> float | None:
    if n <= 0:
        return None
    probability = math.comb(n, hits) / (2**n)
    threshold = probability + 1e-15
    total = 0.0
    for k in range(n + 1):
        p = math.comb(n, k) / (2**n)
        if p <= threshold:
            total += p
    return min(1.0, total)


def _canonical_nonoverlap_rows(rows: list[tuple[dict, dict, dict]]) -> list[tuple[dict, dict, dict]]:
    ordered = sorted(
        rows,
        key=lambda item: _parse_time(item[1].get("source_last_timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    selected: list[tuple[dict, dict, dict]] = []
    last_end: datetime | None = None
    for row in ordered:
        horizon = row[1]
        source = _parse_time(horizon.get("source_last_timestamp"))
        end = _parse_time(horizon.get("forecast_end_timestamp"))
        if source is None or end is None or end <= source:
            continue
        if last_end is not None and source < last_end:
            continue
        selected.append(row)
        last_end = end
    return selected


def _promotion_assessment(horizon_report: dict[str, Any]) -> dict[str, Any]:
    hit_rate = horizon_report.get("kronos_direction_hit_rate")
    p_value = horizon_report.get("kronos_direction_binomial_p_two_sided")
    rank_ic = horizon_report.get("rank_ic_spearman")
    mae_lift = horizon_report.get("kronos_mae_lift_vs_persistence_pct")
    effective_n = int(horizon_report.get("effective_nonoverlap_n") or 0)
    conflict_n = int(horizon_report.get("effective_conflict_n") or 0)
    gates = {
        "effective_n": effective_n >= PROMOTION_MIN_EFFECTIVE_N,
        "conflict_n": conflict_n >= PROMOTION_MIN_CONFLICT_N,
        "direction_hit_rate": hit_rate is not None and hit_rate >= PROMOTION_MIN_DIRECTION_HIT_RATE,
        "direction_binomial_p": p_value is not None and p_value < 0.05,
        "rank_ic_positive": rank_ic is not None and rank_ic > 0.0,
        "mae_beats_persistence": mae_lift is not None and mae_lift > 0.0,
    }
    return {
        "policy_version": KRONOS_PROMOTION_POLICY_VERSION,
        "eligible": all(gates.values()),
        "gates": gates,
        "thresholds": {
            "minimum_effective_nonoverlap_n": PROMOTION_MIN_EFFECTIVE_N,
            "minimum_effective_conflict_n": PROMOTION_MIN_CONFLICT_N,
            "minimum_direction_hit_rate": PROMOTION_MIN_DIRECTION_HIT_RATE,
            "maximum_direction_binomial_p_two_sided": 0.05,
            "rank_ic_must_be_positive": True,
            "mae_lift_vs_persistence_must_be_positive": True,
        },
        "automatic_production_change_allowed": False,
        "requires_human_approval": True,
    }


def evaluate_kronos_pit(records: list[dict[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": KRONOS_RESEARCH_REPORT_VERSION,
        "kind": "RESEARCH_ONLY",
        "production_change_allowed": False,
        "horizons": {},
    }
    for timeframe in ("1h", "4h"):
        rows = []
        for record in records:
            horizon = (record.get("horizons") or {}).get(timeframe) or {}
            outcome = horizon.get("outcome") or {}
            if outcome.get("actual_return_pct") is not None:
                rows.append((record, horizon, outcome))

        if not rows:
            report["horizons"][timeframe] = {
                "available": False,
                "raw_matured_n": 0,
                "effective_nonoverlap_n": 0,
                "overlap_discarded_n": 0,
                "reason": "NO_MATURED_PIT_OUTCOMES",
            }
            continue

        effective_rows = _canonical_nonoverlap_rows(rows)
        pred_returns = [float(h["predicted_terminal_return_pct"]) for _, h, _ in effective_rows]
        actual_returns = [float(o["actual_return_pct"]) for _, _, o in effective_rows]
        rank_ic = None
        if (
            len(effective_rows) >= 3
            and len(set(pred_returns)) > 1
            and len(set(actual_returns)) > 1
        ):
            rank_ic = float(
                pd.Series(pred_returns).rank().corr(pd.Series(actual_returns).rank())
            )

        kronos_hits = [
            bool(o["kronos_direction_hit"])
            for _, _, o in effective_rows
            if o.get("kronos_direction_hit") is not None
        ]
        momentum_hits = [
            bool(o["momentum_direction_hit"])
            for _, _, o in effective_rows
            if o.get("momentum_direction_hit") is not None
        ]
        phase_hits = [
            bool(o["phase_direction_hit"])
            for _, _, o in effective_rows
            if o.get("phase_direction_hit") is not None
        ]
        kronos_errors = [
            float(o["kronos_abs_price_error_pct"])
            for _, _, o in effective_rows
            if o.get("kronos_abs_price_error_pct") is not None
        ]
        persistence_errors = [
            float(o["persistence_abs_price_error_pct"])
            for _, _, o in effective_rows
            if o.get("persistence_abs_price_error_pct") is not None
        ]
        momentum_errors = [
            float(o["momentum_abs_price_error_pct"])
            for _, _, o in effective_rows
            if o.get("momentum_abs_price_error_pct") is not None
        ]

        conflicts = []
        for record, horizon, outcome in effective_rows:
            if (
                _sign(horizon.get("direction_score"), neutral_band=10.0)
                * _sign(horizon.get("phase_direction"), neutral_band=10.0)
                < 0
            ):
                conflicts.append((record, horizon, outcome))
        conflict_kronos_hits = [
            bool(o["kronos_direction_hit"]) for _, _, o in conflicts if o.get("kronos_direction_hit") is not None
        ]
        conflict_phase_hits = [
            bool(o["phase_direction_hit"]) for _, _, o in conflicts if o.get("phase_direction_hit") is not None
        ]

        hit_count = sum(kronos_hits)
        hit_n = len(kronos_hits)
        report["horizons"][timeframe] = {
            "available": True,
            "raw_matured_n": len(rows),
            "effective_nonoverlap_n": len(effective_rows),
            "overlap_discarded_n": len(rows) - len(effective_rows),
            "kronos_direction_hit_rate": _hit_rate(kronos_hits),
            "momentum_direction_hit_rate": _hit_rate(momentum_hits),
            "phase_direction_hit_rate": _hit_rate(phase_hits),
            "kronos_direction_binomial_p_two_sided": _exact_two_sided_binomial_p(hit_count, hit_n),
            "rank_ic_spearman": rank_ic,
            "kronos_terminal_price_mae_pct": _mean(kronos_errors),
            "persistence_terminal_price_mae_pct": _mean(persistence_errors),
            "momentum_terminal_price_mae_pct": _mean(momentum_errors),
            "kronos_mae_lift_vs_persistence_pct": (
                _mean(persistence_errors) - _mean(kronos_errors)
                if persistence_errors and kronos_errors
                else None
            ),
            "effective_conflict_n": len(conflicts),
            "conflict_kronos_hit_rate": _hit_rate(conflict_kronos_hits),
            "conflict_phase_hit_rate": _hit_rate(conflict_phase_hits),
            "research_readiness": {
                "minimum_effective_nonoverlap_n": PROMOTION_MIN_EFFECTIVE_N,
                "minimum_effective_conflict_n": PROMOTION_MIN_CONFLICT_N,
                "effective_sample_ready": len(effective_rows) >= PROMOTION_MIN_EFFECTIVE_N,
                "conflict_sample_ready": len(conflicts) >= PROMOTION_MIN_CONFLICT_N,
            },
        }
    primary = report["horizons"].get(PRIMARY_PROMOTION_TIMEFRAME) or {}
    report["promotion_assessment"] = _promotion_assessment(primary)
    return report
