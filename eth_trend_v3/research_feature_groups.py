from __future__ import annotations

from collections import Counter
from typing import Any

from .forecast import expanding_walk_forward

CORE_FEATURES = ["trend", "crowding", "volatility_risk"]
REGISTERED_GROUPS = {
    "derivatives": ["funding_rate", "open_interest"],
    "options": ["put_call_oi_ratio", "atm_iv_near", "iv_skew_25d_proxy_near", "iv_term_structure_near_next"],
    "macro_rates": ["dxy_return", "us10y_change_bps", "us2y_change_bps", "real10y_change_bps", "yield_curve_10y2y_pp"],
    "crypto_beta": ["btc_return_24h_pct", "ethbtc_return_24h_pct"],
}


def _provider_consistent_rows(rows: list[dict]) -> tuple[list[dict], dict[str, Any]]:
    sources=[str(r.get("derivatives_source")) for r in rows if r.get("derivatives_source")]
    counts=Counter(sources)
    dominant=counts.most_common(1)[0][0] if counts else None
    mixed=len(counts)>1
    out=[]
    for row in rows:
        item=dict(row)
        # OI units/provider semantics are not assumed portable. Keep OI only inside one provider regime.
        if mixed and item.get("derivatives_source") != dominant:
            item["open_interest"]=None
        out.append(item)
    return out, {"derivatives_sources":dict(counts),"dominant_derivatives_source":dominant,"mixed_provider_regime":mixed}


def group_ablation(rows: list[dict]) -> dict:
    normalized, provenance=_provider_consistent_rows(rows)
    baseline=expanding_walk_forward(normalized, CORE_FEATURES)
    baseline_brier=(baseline.get("metrics") or {}).get("brier")
    results={}
    for group, features in REGISTERED_GROUPS.items():
        candidate_features=CORE_FEATURES + features
        result=expanding_walk_forward(normalized,candidate_features)
        brier=(result.get("metrics") or {}).get("brier")
        incremental=(baseline_brier-brier) if baseline_brier is not None and brier is not None else None
        results[group]={
            "features":candidate_features,
            "available":bool(result.get("available")),
            "sample_size":result.get("sample_size",0),
            "metrics":result.get("metrics") or {},
            "reason":result.get("reason"),
            "incremental_brier_vs_core":incremental,
            "survives_research_ablation":bool(incremental is not None and incremental>0 and (result.get("metrics") or {}).get("passes_baseline_gate")),
            "production_eligible":False,
        }
    return {
        "core_features":CORE_FEATURES,
        "baseline":baseline,
        "groups":results,
        "provider_provenance":provenance,
        "research_only":True,
        "promotion_allowed":False,
    }
