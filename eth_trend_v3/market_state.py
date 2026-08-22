from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

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
    mvrv = _num(valuation_raw, "mvrv", "MVRV")
    nupl = _num(valuation_raw, "nupl", "NUPL")
    price_realized = _num(valuation_raw, "price_to_realized", "price_realized_ratio")
    if mvrv is not None:
        vals.append(_clip((1.8 - mvrv) / 1.2 * 100))
    if nupl is not None:
        vals.append(_clip(-nupl / 0.75 * 100))
    if price_realized is not None:
        vals.append(_clip((1.5 - price_realized) * 100))
    valuation = sum(vals) / len(vals) if vals else None

    flow_raw = raw.get("capital_flow") or {}
    fvals = []
    etf = _num(flow_raw, "etf_flow_usd", "etf_netflow")
    exchange = _num(flow_raw, "exchange_netflow_eth", "exchange_netflow")
    stable = _num(flow_raw, "stablecoin_flow_usd", "stablecoin_netflow")
    if etf is not None:
        fvals.append(_clip(etf / 250_000_000 * 100))
    if exchange is not None:
        fvals.append(_clip(-exchange / 100_000 * 100))
    if stable is not None:
        fvals.append(_clip(stable / 500_000_000 * 100))
    capital_flow = sum(fvals) / len(fvals) if fvals else None

    structural_raw = raw.get("structural") or {}
    svals = []
    staking = _num(structural_raw, "staking_netflow_eth", "staking_netflow")
    issuance = _num(structural_raw, "net_issuance_eth", "net_issuance")
    exchange_balance = _num(structural_raw, "exchange_balance_change_pct")
    bridge = _num(structural_raw, "l2_bridge_netflow_eth", "bridge_netflow")
    if staking is not None:
        svals.append(_clip(staking / 50_000 * 100))
    if issuance is not None:
        svals.append(_clip(-issuance / 20_000 * 100))
    if exchange_balance is not None:
        svals.append(_clip(-exchange_balance / 2 * 100))
    if bridge is not None:
        svals.append(_clip(bridge / 100_000 * 100))
    structural = sum(svals) / len(svals) if svals else None

    dimensions = {
        "trend": StateDimension("Trend", trend, float(tech.get("coverage", 0)), "price trend and momentum strength", {"technical_family": tech}),
        "valuation": StateDimension("Valuation", valuation, 100 * len(vals) / 3, "positive=cheap/supportive; negative=expensive", valuation_raw),
        "capital_flow": StateDimension("Capital Flow", capital_flow, 100 * len(fvals) / 3, "positive=net capital support", flow_raw),
        "crowding": StateDimension("Leverage / Crowding", float(result.crowding), 100, "0=uncrowded, 100=extremely crowded", {}),
        "structural_supply": StateDimension("Structural Supply", structural, 100 * len(svals) / 4, "positive=tighter liquid supply", structural_raw),
        "volatility_risk": StateDimension("Volatility / Risk", float(result.volatility), 100, "0=normal risk, 100=extreme volatility risk", {}),
    }
    available = [d for d in dimensions.values() if d.score is not None]
    return {
        "dimensions": {k: v.to_dict() for k, v in dimensions.items()},
        "available_dimensions": len(available),
        "dimension_coverage": round(100 * len(available) / 6, 1),
    }
