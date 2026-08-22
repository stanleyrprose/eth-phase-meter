from __future__ import annotations
import numpy as np


def validate_proxy(proxy: list[float], benchmark: list[float], min_n: int = 60) -> dict:
    n = min(len(proxy), len(benchmark))
    p = np.asarray(proxy[-n:], dtype=float)
    b = np.asarray(benchmark[-n:], dtype=float)
    mask = np.isfinite(p) & np.isfinite(b)
    p = p[mask]
    b = b[mask]

    if len(p) < min_n:
        return {
            "status": "GATED",
            "available": False,
            "kill": False,
            "reason": "INSUFFICIENT_VALIDATION_SAMPLE",
            "n": len(p),
            "label_allowed": "EXPERIMENTAL_PROXY_ONLY",
        }

    corr = float(np.corrcoef(p, b)[0, 1])
    dp = np.diff(p)
    db = np.diff(b)
    turning = float(np.mean(np.sign(dp) == np.sign(db))) if len(dp) else 0.0

    pq = np.quantile(p, [0.1, 0.9])
    bq = np.quantile(b, [0.1, 0.9])
    pe = (p <= pq[0]) | (p >= pq[1])
    be = (b <= bq[0]) | (b >= bq[1])
    overlap = float(np.sum(pe & be) / max(1, np.sum(pe | be)))

    passed = bool(corr >= 0.6 and turning >= 0.55 and overlap >= 0.35)
    return {
        "status": "PASS" if passed else "KILL",
        "available": True,
        "n": len(p),
        "correlation": corr,
        "turning_point_agreement": turning,
        "extreme_zone_overlap": overlap,
        "validation_passed": passed,
        "kill": not passed,
        "reason": "" if passed else "Benchmark correlation/turning-point/extreme-zone gate failed",
        "label_allowed": "ETH-SOPR" if passed else "EXPERIMENTAL_PROXY_ONLY",
    }
