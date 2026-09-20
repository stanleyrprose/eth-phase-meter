#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
OOS_START = pd.Timestamp("2024-07-01T00:00:00Z")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only Kronos-small ETH 4h OOS benchmark after the pretraining cutoff."
    )
    parser.add_argument("--kronos-repo", required=True)
    parser.add_argument("--output-dir", default="eth_reports/kronos_oos")
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--lookback", type=int, default=120)
    parser.add_argument("--pred-len", type=int, default=18)
    parser.add_argument("--stride-bars", type=int, default=18)
    parser.add_argument("--max-points", type=int, default=120)
    parser.add_argument("--device", default=None)
    args = parser.parse_args(argv)
    if min(args.sample_count, args.lookback, args.pred_len, args.stride_bars, args.max_points) < 1:
        parser.error("numeric arguments must be positive")
    return args


def _fetch_binance_4h(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows: list[list] = []
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    session = requests.Session()
    while cursor < end_ms:
        response = session.get(
            BINANCE_KLINES_URL,
            params={
                "symbol": "ETHUSDT",
                "interval": "4h",
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            },
            timeout=20,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + 4 * 3600 * 1000
        if next_cursor <= cursor:
            break
        cursor = next_cursor

    if not rows:
        raise RuntimeError("BINANCE_HISTORY_EMPTY")
    df = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_vol",
            "trades",
            "taker_buy_vol",
            "taker_buy_quote",
            "ignore",
        ],
    )
    df["timestamps"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_timestamp"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    numeric = ["open", "high", "low", "close", "volume", "quote_vol"]
    for column in numeric:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = (
        df[df["close_timestamp"] <= pd.Timestamp(end)]
        .dropna(subset=numeric)
        .drop_duplicates("timestamps")
        .sort_values("timestamps")
        .reset_index(drop=True)
    )
    return df


def _repo_sha(repo: Path) -> str | None:
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() or None if completed.returncode == 0 else None


def _direction_hit(predicted: float, actual: float) -> bool | None:
    if predicted == 0 or actual == 0:
        return None
    return (predicted > 0) == (actual > 0)


def _binomial_p_two_sided(hits: int, n: int) -> float | None:
    if n <= 0:
        return None
    observed = math.comb(n, hits) / (2**n)
    return min(
        1.0,
        sum(
            math.comb(n, k) / (2**n)
            for k in range(n + 1)
            if math.comb(n, k) / (2**n) <= observed + 1e-15
        ),
    )


def _select_points(
    df: pd.DataFrame,
    *,
    lookback: int,
    pred_len: int,
    stride_bars: int,
    max_points: int,
) -> list[int]:
    first_oos = int(df.index[df["timestamps"] >= OOS_START][0])
    start_idx = max(lookback - 1, first_oos)
    indices = list(range(start_idx, len(df) - pred_len, stride_bars))
    if len(indices) > max_points:
        selected = np.linspace(0, len(indices) - 1, max_points, dtype=int)
        indices = [indices[int(i)] for i in selected]
    return indices


def _run_prediction(
    predictor,
    torch,
    frame: pd.DataFrame,
    future_timestamps: pd.Series,
    *,
    pred_len: int,
    sample_count: int,
    seed_base: int,
) -> list[float]:
    values = frame[["open", "high", "low", "close", "volume", "quote_vol"]].copy()
    values.columns = ["open", "high", "low", "close", "volume", "amount"]
    timestamps = frame["timestamps"].reset_index(drop=True)
    last_close = float(values.iloc[-1]["close"])
    returns: list[float] = []
    for sample in range(sample_count):
        seed = seed_base + sample
        np.random.seed(seed)
        torch.manual_seed(seed)
        pred = predictor.predict(
            df=values,
            x_timestamp=timestamps,
            y_timestamp=future_timestamps,
            pred_len=pred_len,
            T=1.0,
            top_p=0.9,
            sample_count=1,
            verbose=False,
        )
        terminal = float(pred["close"].astype(float).iloc[-1])
        returns.append((terminal / last_close - 1.0) * 100.0)
    return returns


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    kronos_repo = Path(args.kronos_repo).expanduser().resolve()
    if not (kronos_repo / "model").exists():
        raise RuntimeError("KRONOS_REPO_INVALID")
    sys.path.insert(0, str(kronos_repo))

    import torch
    from model import Kronos, KronosPredictor, KronosTokenizer

    end = pd.Timestamp.now(tz="UTC")
    history_start = OOS_START - dt.timedelta(days=30)
    df = _fetch_binance_4h(history_start, end)
    points = _select_points(
        df,
        lookback=args.lookback,
        pred_len=args.pred_len,
        stride_bars=max(args.stride_bars, args.pred_len),
        max_points=args.max_points,
    )
    if not points:
        raise RuntimeError("NO_OOS_POINTS")

    codec_id = "NeoQuasar/" + "Kronos-Tokenizer-base"
    model_id = "NeoQuasar/" + "Kronos-small"
    codec = KronosTokenizer.from_pretrained(codec_id)
    model = Kronos.from_pretrained(model_id)
    codec.eval()
    model.eval()
    predictor = KronosPredictor(model, codec, device=args.device, max_context=512)

    rows = []
    for sequence, index in enumerate(points):
        frame = df.iloc[index - args.lookback + 1 : index + 1].reset_index(drop=True)
        target = df.iloc[index + args.pred_len]
        future = df.iloc[index + 1 : index + args.pred_len + 1]["timestamps"].reset_index(drop=True)
        source_close = float(frame.iloc[-1]["close"])
        actual_close = float(target["close"])
        actual_return = (actual_close / source_close - 1.0) * 100.0
        trailing_start = float(frame.iloc[-7]["close"])
        momentum_return = (source_close / trailing_start - 1.0) * 100.0
        samples = _run_prediction(
            predictor,
            torch,
            frame,
            future,
            pred_len=args.pred_len,
            sample_count=args.sample_count,
            seed_base=260919 + sequence * 10,
        )
        kronos_return = float(np.median(samples))
        kronos_close = source_close * (1.0 + kronos_return / 100.0)
        momentum_close = source_close * (1.0 + momentum_return / 100.0)
        rows.append(
            {
                "source_timestamp": frame.iloc[-1]["timestamps"].isoformat(),
                "target_timestamp": target["timestamps"].isoformat(),
                "source_close": source_close,
                "actual_close": actual_close,
                "actual_return_pct": actual_return,
                "kronos_return_pct": kronos_return,
                "kronos_samples_pct": samples,
                "kronos_direction_hit": _direction_hit(kronos_return, actual_return),
                "momentum_return_pct": momentum_return,
                "momentum_direction_hit": _direction_hit(momentum_return, actual_return),
                "kronos_abs_price_error_pct": abs(kronos_close / actual_close - 1.0) * 100.0,
                "persistence_abs_price_error_pct": abs(source_close / actual_close - 1.0) * 100.0,
                "momentum_abs_price_error_pct": abs(momentum_close / actual_close - 1.0) * 100.0,
            }
        )
        if (sequence + 1) % 10 == 0 or sequence + 1 == len(points):
            print(f"OOS progress {sequence + 1}/{len(points)}", flush=True)

    kronos_hits = [bool(row["kronos_direction_hit"]) for row in rows if row["kronos_direction_hit"] is not None]
    momentum_hits = [bool(row["momentum_direction_hit"]) for row in rows if row["momentum_direction_hit"] is not None]
    pred_returns = pd.Series([row["kronos_return_pct"] for row in rows])
    actual_returns = pd.Series([row["actual_return_pct"] for row in rows])
    rank_ic = float(pred_returns.rank().corr(actual_returns.rank())) if len(rows) >= 3 else None
    kronos_mae = _mean([row["kronos_abs_price_error_pct"] for row in rows])
    persistence_mae = _mean([row["persistence_abs_price_error_pct"] for row in rows])
    momentum_mae = _mean([row["momentum_abs_price_error_pct"] for row in rows])

    report = {
        "schema_version": "kronos-oos-benchmark-v1",
        "kind": "RESEARCH_ONLY",
        "production_change_allowed": False,
        "asset": "ETHUSDT",
        "source": "Binance spot 4h closed candles",
        "oos_start": OOS_START.isoformat(),
        "pretraining_cutoff_assumption": "2024-06-30 or earlier; OOS starts 2024-07-01",
        "model": {
            "name": "Kronos-small",
            "model_id": model_id,
            "codec_id": codec_id,
            "repo_sha": _repo_sha(kronos_repo),
            "device": str(predictor.device),
        },
        "configuration": {
            "lookback": args.lookback,
            "pred_len": args.pred_len,
            "horizon_hours": args.pred_len * 4,
            "sample_count": args.sample_count,
            "stride_bars": max(args.stride_bars, args.pred_len),
            "selected_points": len(rows),
            "overlapping_targets": False,
        },
        "metrics": {
            "n": len(rows),
            "kronos_direction_hit_rate": float(np.mean(kronos_hits)) if kronos_hits else None,
            "momentum_direction_hit_rate": float(np.mean(momentum_hits)) if momentum_hits else None,
            "kronos_direction_binomial_p_two_sided": _binomial_p_two_sided(
                sum(kronos_hits), len(kronos_hits)
            ),
            "rank_ic_spearman": rank_ic,
            "kronos_terminal_price_mae_pct": kronos_mae,
            "persistence_terminal_price_mae_pct": persistence_mae,
            "momentum_terminal_price_mae_pct": momentum_mae,
            "kronos_mae_lift_vs_persistence_pct": (
                persistence_mae - kronos_mae
                if persistence_mae is not None and kronos_mae is not None
                else None
            ),
        },
        "rows": rows,
        "interpretation_guardrail": (
            "Sampling agreement is not a calibrated probability. "
            "This benchmark is diagnostic and cannot promote Kronos into production."
        ),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }

    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(rows).drop(columns=["kronos_samples_pct"]).to_csv(out / "rows.csv", index=False)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
