from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .dataset import canonicalize_pit_records


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" UTC", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def enrich_staking_netflow(
    raw: dict,
    history_records: list[dict],
    *,
    target_hours: float = 24.0,
    tolerance_hours: float = 4.5,
) -> dict:
    """Derive 24h staking liquidity flow from point-in-time cumulative counters.

    Current and prior counters are Etherscan snapshots:
      deposits = change in the mainnet Beacon deposit-contract balance;
      withdrawals = change in Etherscan WithdrawnTotal.

    No history -> no flow. Counter regressions -> no flow. The operation mutates
    ``raw['structural']`` only with auditable derived fields and never imputes zero.
    """
    structural = dict(raw.get("structural") or {})
    raw["structural"] = structural

    current_deposits = _num(structural.get("staking_deposit_contract_balance_eth"))
    current_withdrawn = _num(structural.get("beacon_withdrawn_total_eth"))
    current_at = _parse_time(structural.get("staking_counters_observed_at"))
    if current_at is None:
        current_at = _parse_time(((raw.get("_meta") or {}).get("structural") or {}).get("observed_at"))

    if current_deposits is None or current_withdrawn is None or current_at is None:
        structural["_staking_flow_status"] = "COUNTERS_UNAVAILABLE"
        return raw

    candidates = []
    for record in canonicalize_pit_records(history_records, timeframe="4h"):
        prior_raw = record.get("raw_payload") or {}
        prior = prior_raw.get("structural") or {}
        prior_deposits = _num(prior.get("staking_deposit_contract_balance_eth"))
        prior_withdrawn = _num(prior.get("beacon_withdrawn_total_eth"))
        prior_at = _parse_time(prior.get("staking_counters_observed_at"))
        if prior_at is None:
            prior_at = _parse_time(record.get("observed_at") or record.get("event_time"))
        if prior_deposits is None or prior_withdrawn is None or prior_at is None:
            continue
        age_hours = (current_at - prior_at).total_seconds() / 3600.0
        if age_hours <= 0 or abs(age_hours - target_hours) > tolerance_hours:
            continue
        candidates.append((abs(age_hours - target_hours), prior_at, age_hours, prior_deposits, prior_withdrawn))

    if not candidates:
        structural["_staking_flow_status"] = "WAITING_FOR_24H_BASELINE"
        return raw

    _, prior_at, age_hours, prior_deposits, prior_withdrawn = min(candidates, key=lambda item: item[0])
    deposits = current_deposits - prior_deposits
    withdrawals = current_withdrawn - prior_withdrawn
    if deposits < -1e-9 or withdrawals < -1e-9:
        structural["_staking_flow_status"] = "COUNTER_REGRESSION"
        return raw

    netflow = deposits - withdrawals
    structural["staking_deposits_24h_eth"] = deposits
    structural["beacon_withdrawals_24h_eth"] = withdrawals
    structural["staking_netflow_etherscan_eth"] = netflow
    structural["staking_flow_window_hours"] = age_hours
    structural["staking_flow_prior_observed_at"] = prior_at.isoformat()

    existing = _num(structural.get("staking_netflow_eth"))
    source_text = str(structural.get("_source") or "")
    if "explicit adapter" in source_text.lower():
        # Explicit user-provided adapters remain highest precedence. Preserve the
        # independent Etherscan result only as a cross-provider diagnostic.
        structural["staking_netflow_parallel_etherscan_eth"] = netflow
    else:
        # Free PIT-derived Etherscan is the baseline. Preserve any optional Dune
        # value as a parallel diagnostic rather than letting it overwrite baseline.
        if existing is not None:
            structural["staking_netflow_parallel_provider_eth"] = existing
        structural["staking_netflow_eth"] = netflow
        structural["staking_netflow_source"] = "Etherscan PIT delta"
    structural["_staking_flow_status"] = "READY"
    return raw
