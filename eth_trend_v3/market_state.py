from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any
from .engine import crowding_coverage

DIMENSION_SCHEMA_VERSIONS = {
    "trend": "trend-v1",
    "valuation": "valuation-v2-defi-tvl",
    "capital_flow": "capital-flow-v3-usd-inflows",
    "crowding": "crowding-v2-dte48",
    "structural_supply": "structural-supply-v3-free-baseline",
    "volatility_risk": "volatility-risk-v1",
}

@dataclass
class StateDimension:
    name: str
    score: float | None
    coverage: float
    semantic: str
    components: dict[str, Any]
    def to_dict(self):
        return asdict(self)

def _clip(v, lo=-100.0, hi=100.0):
    return max(lo, min(hi, float(v)))

def _num(d: dict, *names):
    for n in names:
        v = d.get(n)
        if isinstance(v, (int, float)):
            return float(v)
    return None

def build_market_state(raw: dict, result) -> dict:
    fam = result.quality.get("families", {})
    tech = fam.get("Technical", {})
    nominal = float(tech.get("nominal") or 40)
    trend = _clip(100 * float(tech.get("contribution", 0)) / nominal) if tech.get("active", 0) else None

    valuation_raw = raw.get("valuation") or {}
    vals = []
    # MVRV/price-to-realized/NUPL occupy one realized-value slot; they are
    # correlated views of the same valuation family and must never count twice.
    mvrv = _num(valuation_raw, "mvrv", "MVRV", "price_to_realized", "price_realized_ratio")
    nupl = _num(valuation_raw, "nupl", "NUPL")
    mcap_to_tvl = _num(valuation_raw, "mcap_to_tvl")
    if mvrv is not None:
        vals.append(_clip((1.8 - mvrv) / 1.2 * 100))
    elif nupl is not None:
        vals.append(_clip(-nupl / 0.75 * 100))
    if mcap_to_tvl is not None:
        # Descriptive heuristic only: ~6x is neutral, ~2x supportive, ~10x rich.
        # This is a market-state score, not a probability or valuation target.
        vals.append(_clip((6.0 - mcap_to_tvl) / 4.0 * 100))
    valuation = sum(vals) / len(vals) if vals else None

    flow_raw = raw.get("capital_flow") or {}
    fvals = []
    etf = _num(flow_raw, "etf_flow_usd", "etf_netflow")
    exchange = _num(flow_raw, "exchange_netflow_eth", "exchange_netflow")
    stable_supply = _num(flow_raw, "stablecoin_supply_change_usd")
    defi_inflows = _num(flow_raw, "defi_inflows_24h_usd")
    if etf is not None:
        fvals.append(_clip(etf / 250_000_000 * 100))
    if exchange is not None:
        fvals.append(_clip(-exchange / 100_000 * 100))
    if stable_supply is not None:
        fvals.append(_clip(stable_supply / 500_000_000 * 100))
    if defi_inflows is not None:
        # Price-neutral 24h net asset inflow. ±$250M maps to the score bounds,
        # roughly 0.5% of current Ethereum DeFi TVL and intentionally conservative.
        fvals.append(_clip(defi_inflows / 250_000_000 * 100))
    capital_flow = sum(fvals) / len(fvals) if fvals else None

    structural_raw = raw.get("structural") or {}
    svals = []
    staking = _num(structural_raw, "staking_netflow_eth", "staking_netflow")
    staking_queue = _num(structural_raw, "staking_queue_imbalance_pct")
    issuance = _num(structural_raw, "net_issuance_eth", "net_issuance")
    exchange_balance = _num(structural_raw, "exchange_balance_change_pct")
    if staking is not None:
        svals.append(_clip(staking / 50_000 * 100))
    elif staking_queue is not None:
        # Queue imbalance is a forward staking-pressure proxy, not realized flow.
        # It occupies the same staking-evidence slot only when realized flow is absent.
        svals.append(_clip(staking_queue))
    if issuance is not None:
        svals.append(_clip(-issuance / 20_000 * 100))
    if exchange_balance is not None:
        svals.append(_clip(-exchange_balance / 2 * 100))
    # Bridge/L2 flow may remain in components as optional enrichment, but there is
    # no stable credential-free production source, so it is not a nominal slot.
    structural = sum(svals) / len(svals) if svals else None

    dimensions = {
        "trend": StateDimension("Trend", trend, float(tech.get("coverage", 0)), "price trend and momentum strength", {"technical_family": tech}),
        "valuation": StateDimension("Valuation", valuation, 100 * len(vals) / 2, "positive=cheap/supportive; negative=expensive", valuation_raw),
        "capital_flow": StateDimension("Capital Flow", capital_flow, 100 * len(fvals) / 4, "positive=net capital support", flow_raw),
        "crowding": StateDimension("Leverage / Crowding", float(result.crowding), crowding_coverage(raw), "0=uncrowded, 100=extremely crowded", {}),
        "structural_supply": StateDimension("Structural Supply", structural, 100 * len(svals) / 3, "positive=tighter liquid supply or stronger pending staking pressure", structural_raw),
        "volatility_risk": StateDimension("Volatility / Risk", float(result.volatility), 100, "0=normal risk, 100=extreme volatility risk", {}),
    }
    available = [d for d in dimensions.values() if d.score is not None]
    return {
        "dimensions": {k: v.to_dict() for k, v in dimensions.items()},
        "dimension_versions": dict(DIMENSION_SCHEMA_VERSIONS),
        "available_dimensions": len(available),
        "dimension_coverage": round(100 * len(available) / 6, 1),
    }
