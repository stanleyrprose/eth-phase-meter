from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .dataset import canonicalize_pit_records

POLICIES = ("fixed_exposure", "absolute_conviction", "vol_targeted_conviction")
REVIEW_CHECKPOINT_INTERVALS = 250


@dataclass(frozen=True)
class SizingResearchConfig:
    review_checkpoint_intervals: int = REVIEW_CHECKPOINT_INTERVALS
    gross_limit: float = 0.25
    target_ann_vol: float = 0.60
    cost_bps: float = 10.0
    vol_window: int = 12
    vol_min_periods: int = 6
    max_nominal_gap_hours: float = 4.5
    coverage_threshold: float = 80.0
    bootstrap_samples: int = 2000
    bootstrap_block: int = 6
    seed: int = 42


def _parse_time(value: Any) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(
        str(value).replace(" UTC", "+00:00"),
        utc=True,
        errors="coerce",
    )
    if pd.isna(parsed):
        return None
    return parsed


def _record_row(record: dict[str, Any]) -> dict[str, Any] | None:
    metric = record.get("metric_value") or {}
    if metric.get("timeframe") != "4h":
        return None
    try:
        price = float(metric.get("price"))
        direction = float(metric.get("final_direction"))
        coverage = float(record.get("coverage") or 0.0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    observed = _parse_time(record.get("observed_at") or record.get("event_time"))
    if observed is None:
        return None
    nominal = _parse_time(record.get("schedule_nominal_time")) or observed
    regime = (record.get("regime") or {}).get("regime") or metric.get("rule_regime") or "UNKNOWN"

    return {
        "observed_at": observed,
        "nominal_time": nominal,
        "price": price,
        "direction": direction,
        "coverage": coverage,
        "regime": str(regime),
        "github_event": str(record.get("github_event") or "legacy"),
        "workflow_run_id": str(record.get("workflow_run_id") or ""),
        "raw_payload_hash": record.get("raw_payload_hash"),
    }


def build_sizing_intervals(
    records: list[dict[str, Any]],
    config: SizingResearchConfig | None = None,
) -> pd.DataFrame:
    """Build one forward return interval per canonical scheduled 4h PIT bucket.

    The signal and metadata come only from the current PIT record. The realized return
    uses the next canonical bucket's price. Trailing volatility is shifted so the
    current interval return is never used to size the same interval.
    """
    config = config or SizingResearchConfig()
    canonical = canonicalize_pit_records(records, timeframe="4h")
    rows = [_record_row(record) for record in canonical]
    rows = [row for row in rows if row is not None]
    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows).sort_values("nominal_time").reset_index(drop=True)
    frame["next_nominal_time"] = frame["nominal_time"].shift(-1)
    frame["next_observed_at"] = frame["observed_at"].shift(-1)
    frame["next_price"] = frame["price"].shift(-1)
    frame["nominal_gap_hours"] = (
        frame["next_nominal_time"] - frame["nominal_time"]
    ).dt.total_seconds() / 3600.0
    frame["asset_return"] = frame["next_price"] / frame["price"] - 1.0

    frame = frame[
        frame["asset_return"].notna()
        & frame["nominal_gap_hours"].gt(0)
        & frame["nominal_gap_hours"].le(config.max_nominal_gap_hours)
    ].copy()
    frame["conviction"] = (frame["direction"] / 100.0).clip(-1.0, 1.0)

    past_returns = frame["asset_return"].shift(1)
    periods_per_year = 6.0 * 365.25
    frame["trailing_ann_vol"] = (
        past_returns.rolling(
            config.vol_window,
            min_periods=config.vol_min_periods,
        ).std(ddof=1)
        * np.sqrt(periods_per_year)
    )
    return frame.reset_index(drop=True)


def _policy_weights(frame: pd.DataFrame, config: SizingResearchConfig) -> dict[str, pd.Series]:
    conviction = frame["conviction"].astype(float)
    fixed = np.sign(conviction) * config.gross_limit
    absolute = conviction * config.gross_limit
    vol_scale = (config.target_ann_vol / frame["trailing_ann_vol"]).replace(
        [np.inf, -np.inf],
        np.nan,
    )
    vol_targeted = (absolute * vol_scale).clip(-config.gross_limit, config.gross_limit)
    return {
        "fixed_exposure": pd.Series(fixed, index=frame.index, dtype=float),
        "absolute_conviction": pd.Series(absolute, index=frame.index, dtype=float),
        "vol_targeted_conviction": pd.Series(vol_targeted, index=frame.index, dtype=float),
    }


def _policy_returns(
    frame: pd.DataFrame,
    weight: pd.Series,
    *,
    cost_bps: float,
) -> pd.DataFrame:
    previous = weight.shift(1).fillna(0.0)
    turnover = (weight - previous).abs()
    cost = turnover * (cost_bps / 10000.0)
    gross = weight * frame["asset_return"]
    net = gross - cost
    return pd.DataFrame(
        {
            "weight": weight,
            "turnover": turnover,
            "cost": cost,
            "gross_return": gross,
            "net_return": net,
        },
        index=frame.index,
    )


def _total_return(returns: pd.Series) -> float:
    return float((1.0 + returns.fillna(0.0)).prod() - 1.0)


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    if equity.empty:
        return 0.0
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def _annualized_sharpe(returns: pd.Series, median_gap_hours: float) -> float | None:
    clean = returns.dropna()
    if len(clean) < 2:
        return None
    std = float(clean.std(ddof=1))
    if std <= 0 or median_gap_hours <= 0:
        return None
    periods_per_year = (365.25 * 24.0) / median_gap_hours
    return float(clean.mean() / std * np.sqrt(periods_per_year))


def _metrics(frame: pd.DataFrame, policy: pd.DataFrame) -> dict[str, Any]:
    median_gap = float(frame["nominal_gap_hours"].median())
    net = policy["net_return"]
    sharpe = _annualized_sharpe(net, median_gap)
    return {
        "n_intervals": int(len(frame)),
        "total_return_pct": round(_total_return(net) * 100.0, 4),
        "max_drawdown_pct": round(_max_drawdown(net) * 100.0, 4),
        "annualized_sharpe_descriptive": round(sharpe, 4) if sharpe is not None else None,
        "avg_abs_exposure_pct": round(float(policy["weight"].abs().mean()) * 100.0, 4),
        "total_turnover": round(float(policy["turnover"].sum()), 4),
        "estimated_cost_pct_of_equity": round(float(policy["cost"].sum()) * 100.0, 4),
        "mean_net_return_bps": round(float(net.mean()) * 10000.0, 4),
        "positive_interval_rate": round(float((net > 0).mean()), 4),
    }


def _moving_block_mean_ci(
    diff: np.ndarray,
    *,
    samples: int,
    block: int,
    seed: int,
) -> tuple[float, float] | None:
    clean = np.asarray(diff, dtype=float)
    clean = clean[np.isfinite(clean)]
    n = len(clean)
    if n < max(block * 2, 12):
        return None
    rng = np.random.default_rng(seed)
    starts = np.arange(0, n - block + 1)
    means = np.empty(samples, dtype=float)
    blocks_needed = int(np.ceil(n / block))
    for index in range(samples):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate([clean[start : start + block] for start in chosen])[:n]
        means[index] = sample.mean()
    low, high = np.quantile(means, [0.025, 0.975])
    return float(low), float(high)


def _conviction_diagnostic(frame: pd.DataFrame) -> dict[str, Any]:
    magnitude = frame["conviction"].abs().astype(float)
    signed_outcome = np.sign(frame["conviction"].astype(float)) * frame["asset_return"].astype(float)
    if magnitude.nunique(dropna=True) < 2 or signed_outcome.nunique(dropna=True) < 2:
        pearson = None
        spearman = None
    else:
        pearson = magnitude.corr(signed_outcome, method="pearson")
        spearman = magnitude.corr(signed_outcome, method="spearman")

    bucket_code = pd.qcut(magnitude, 3, labels=False, duplicates="drop")
    buckets: list[dict[str, Any]] = []
    names = ("low", "mid", "high")
    for code in sorted(pd.Series(bucket_code).dropna().unique()):
        mask = bucket_code == code
        values = signed_outcome[mask]
        magnitudes = magnitude[mask]
        idx = int(code)
        buckets.append(
            {
                "bucket": names[idx] if idx < len(names) else f"q{idx + 1}",
                "n": int(mask.sum()),
                "min_abs_conviction": round(float(magnitudes.min()), 4),
                "max_abs_conviction": round(float(magnitudes.max()), 4),
                "mean_signed_outcome_bps": round(float(values.mean()) * 10000.0, 4),
                "positive_directional_rate": round(float((values > 0).mean()), 4),
            }
        )

    monotonic = None
    high_minus_low = None
    if len(buckets) >= 2:
        high_minus_low = round(
            buckets[-1]["mean_signed_outcome_bps"] - buckets[0]["mean_signed_outcome_bps"],
            4,
        )
    if len(buckets) == 3:
        means = [row["mean_signed_outcome_bps"] for row in buckets]
        monotonic = bool(means[0] <= means[1] <= means[2])

    return {
        "pearson_abs_conviction_vs_signed_outcome": (
            round(float(pearson), 4) if pearson is not None and pd.notna(pearson) else None
        ),
        "spearman_abs_conviction_vs_signed_outcome": (
            round(float(spearman), 4) if spearman is not None and pd.notna(spearman) else None
        ),
        "high_minus_low_mean_signed_outcome_bps": high_minus_low,
        "monotonic_increase_across_tertiles": monotonic,
        "tertiles": buckets,
    }


def _regime_sensitivity(frame: pd.DataFrame, policy: pd.DataFrame) -> dict[str, Any]:
    merged = frame[["regime"]].copy()
    merged["net_return"] = policy["net_return"]
    merged["abs_exposure"] = policy["weight"].abs()
    result: dict[str, Any] = {}
    for regime, group in merged.groupby("regime", dropna=False):
        result[str(regime)] = {
            "n": int(len(group)),
            "total_return_pct": round(_total_return(group["net_return"]) * 100.0, 4),
            "mean_net_return_bps": round(float(group["net_return"].mean()) * 10000.0, 4),
            "avg_abs_exposure_pct": round(float(group["abs_exposure"].mean()) * 100.0, 4),
        }
    return result


def _benchmark_cohort(
    intervals: pd.DataFrame,
    *,
    config: SizingResearchConfig,
    name: str,
    minimum_coverage: float | None,
) -> dict[str, Any]:
    frame = intervals.copy()
    if minimum_coverage is not None:
        frame = frame[frame["coverage"] >= minimum_coverage].copy()
    frame = frame[frame["trailing_ann_vol"].notna()].copy().reset_index(drop=True)

    if frame.empty:
        return {
            "cohort": name,
            "minimum_coverage": minimum_coverage,
            "n_intervals": 0,
            "conviction_diagnostic": {},
            "metrics": {},
            "regime_sensitivity": {},
            "paired_vs_fixed": {},
        }

    weights = _policy_weights(frame, config)
    policies = {
        policy_name: _policy_returns(frame, weight, cost_bps=config.cost_bps)
        for policy_name, weight in weights.items()
    }
    metrics = {key: _metrics(frame, value) for key, value in policies.items()}

    fixed = policies["fixed_exposure"]["net_return"].to_numpy()
    paired = {}
    for policy_name in ("absolute_conviction", "vol_targeted_conviction"):
        diff = policies[policy_name]["net_return"].to_numpy() - fixed
        ci = _moving_block_mean_ci(
            diff,
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=config.seed,
        )
        paired[policy_name] = {
            "mean_delta_vs_fixed_bps_per_interval": round(float(np.mean(diff)) * 10000.0, 4),
            "moving_block_95pct_ci_bps": (
                [round(ci[0] * 10000.0, 4), round(ci[1] * 10000.0, 4)]
                if ci is not None
                else None
            ),
            "ci_excludes_zero": bool(ci and (ci[0] > 0 or ci[1] < 0)),
        }

    return {
        "cohort": name,
        "minimum_coverage": minimum_coverage,
        "n_intervals": int(len(frame)),
        "conviction_diagnostic": _conviction_diagnostic(frame),
        "metrics": metrics,
        "regime_sensitivity": {
            key: _regime_sensitivity(frame, value) for key, value in policies.items()
        },
        "paired_vs_fixed": paired,
    }


def run_sizing_research(
    records: list[dict[str, Any]],
    config: SizingResearchConfig | None = None,
) -> dict[str, Any]:
    config = config or SizingResearchConfig()
    intervals = build_sizing_intervals(records, config)
    raw_valid_n = int(len(intervals))
    checkpoint_reached = raw_valid_n >= config.review_checkpoint_intervals

    cohorts = [
        _benchmark_cohort(
            intervals,
            config=config,
            name="all_pit_clean",
            minimum_coverage=None,
        ),
        _benchmark_cohort(
            intervals,
            config=config,
            name="coverage_ge_threshold",
            minimum_coverage=config.coverage_threshold,
        ),
    ]

    cost_sensitivity: dict[str, Any] = {}
    for cost_bps in (5.0, 10.0, 20.0):
        cost_config = SizingResearchConfig(
            **{**asdict(config), "cost_bps": cost_bps}
        )
        cohort = _benchmark_cohort(
            intervals,
            config=cost_config,
            name="all_pit_clean",
            minimum_coverage=None,
        )
        cost_sensitivity[str(int(cost_bps))] = {
            policy: {
                "total_return_pct": metrics.get("total_return_pct"),
                "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                "annualized_sharpe_descriptive": metrics.get("annualized_sharpe_descriptive"),
            }
            for policy, metrics in cohort.get("metrics", {}).items()
        }

    return {
        "contract_version": "eth-sizing-research-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "signal_proxy": "metric_value.final_direction / 100",
        "data_source": "canonical durable PIT records",
        "review_checkpoint_target_intervals": config.review_checkpoint_intervals,
        "review_checkpoint_reached": checkpoint_reached,
        "status": (
            "READY_FOR_HUMAN_SIZING_REVIEW"
            if checkpoint_reached
            else "WAIT_FOR_MORE_PIT_SIZING_EVIDENCE"
        ),
        "raw_valid_intervals": raw_valid_n,
        "canonical_4h_records": int(
            len(canonicalize_pit_records(records, timeframe="4h"))
        ),
        "config": asdict(config),
        "cohorts": cohorts,
        "cost_sensitivity_bps": cost_sensitivity,
        "automatic_sizing_promotion_allowed": False,
        "automatic_shadow_allowed": False,
        "automatic_production_allowed": False,
        "paper_execution_allowed": False,
        "live_execution_allowed": False,
        "limitations": [
            "Review checkpoint is a human-review cadence threshold, not a statistical promotion gate.",
            "Rule direction is a research sizing proxy, not a production-approved probability.",
            "A positive backtest snapshot cannot auto-promote sizing.",
            "Formal review must inspect monotonicity, paired uncertainty, regime stability, and cost sensitivity across time.",
        ],
    }
