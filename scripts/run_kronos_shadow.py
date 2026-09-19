#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HUB = "NeoQuasar/"
MODEL_CONFIGS = {
    "mini": {"model": _HUB + "Kronos-mini", "codec": _HUB + "Kronos-Tokenizer-2k", "max_context": 2048},
    "small": {"model": _HUB + "Kronos-small", "codec": _HUB + "Kronos-Tokenizer-base", "max_context": 512},
    "base": {"model": _HUB + "Kronos-base", "codec": _HUB + "Kronos-Tokenizer-base", "max_context": 512},
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run research-only Kronos ETH forward-path evidence.")
    parser.add_argument("--kronos-repo", required=True)
    parser.add_argument("--input-1h", required=True)
    parser.add_argument("--input-4h", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", choices=sorted(MODEL_CONFIGS), default="small")
    parser.add_argument("--device", default=None)
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--lookback-1h", type=int, default=160)
    parser.add_argument("--lookback-4h", type=int, default=120)
    parser.add_argument("--pred-len-1h", type=int, default=12)
    parser.add_argument("--pred-len-4h", type=int, default=18)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.9)
    args = parser.parse_args(argv)
    if args.sample_count < 1:
        parser.error("--sample-count must be >= 1")
    return args


def _load_frame(path: Path, lookback: int) -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_csv(path)
    required = {"timestamps", "open", "high", "low", "close", "volume", "amount"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"KRONOS_INPUT_MISSING_COLUMNS: {sorted(missing)}")
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    df = df.sort_values("timestamps").drop_duplicates("timestamps").tail(lookback).reset_index(drop=True)
    if len(df) < min(50, lookback):
        raise RuntimeError(f"KRONOS_INPUT_TOO_SHORT: rows={len(df)} lookback={lookback}")
    values = df[["open", "high", "low", "close", "volume", "amount"]]
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise RuntimeError("KRONOS_INPUT_NONFINITE")
    return values.astype(float), df["timestamps"].reset_index(drop=True)


def _future_timestamps(last: pd.Timestamp, timeframe: str, pred_len: int) -> pd.Series:
    hours = 1 if timeframe == "1h" else 4
    step = dt.timedelta(hours=hours)
    return pd.Series(pd.date_range(start=last + step, periods=pred_len, freq=f"{hours}h"))


def _direction_score(return_pct: float, scale_pct: float) -> float:
    return round(100.0 * math.tanh(return_pct / scale_pct), 3)


def _repo_sha(repo: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _run_horizon(
    predictor,
    torch,
    *,
    input_path: Path,
    timeframe: str,
    lookback: int,
    pred_len: int,
    sample_count: int,
    temperature: float,
    top_p: float,
) -> dict:
    frame, timestamps = _load_frame(input_path, lookback)
    future = _future_timestamps(timestamps.iloc[-1], timeframe, pred_len)
    last_close = float(frame.iloc[-1]["close"])
    returns: list[float] = []
    end_closes: list[float] = []
    path_ranges: list[float] = []

    for index in range(sample_count):
        seed = 260919 + index
        np.random.seed(seed)
        torch.manual_seed(seed)
        pred = predictor.predict(
            df=frame,
            x_timestamp=timestamps,
            y_timestamp=future,
            pred_len=pred_len,
            T=temperature,
            top_p=top_p,
            sample_count=1,
            verbose=False,
        )
        close = pred["close"].astype(float)
        terminal = float(close.iloc[-1])
        end_closes.append(terminal)
        returns.append((terminal / last_close - 1.0) * 100.0)
        path_ranges.append((float(close.max()) / float(close.min()) - 1.0) * 100.0)

    median_return = float(np.median(returns))
    scale = 3.0 if timeframe == "1h" else 6.0
    positive_share = 100.0 * sum(value > 0 for value in returns) / len(returns)
    directional_agreement = max(positive_share, 100.0 - positive_share)
    return {
        "timeframe": timeframe,
        "source_last_timestamp": timestamps.iloc[-1].isoformat(),
        "source_last_close": last_close,
        "lookback": len(frame),
        "pred_len": pred_len,
        "forecast_end_timestamp": future.iloc[-1].isoformat(),
        "sample_count": sample_count,
        "terminal_return_samples_pct": [round(x, 6) for x in returns],
        "median_terminal_return_pct": round(median_return, 6),
        "mean_terminal_return_pct": round(float(np.mean(returns)), 6),
        "terminal_return_std_pct": round(float(np.std(returns)), 6),
        "up_sample_share_pct": round(positive_share, 3),
        "sample_directional_agreement_pct": round(directional_agreement, 3),
        "median_terminal_close": round(float(np.median(end_closes)), 6),
        "mean_path_range_pct": round(float(np.mean(path_ranges)), 6),
        "direction_score": _direction_score(median_return, scale),
        "direction_score_normalization": {
            "method": "100*tanh(median_terminal_return_pct/scale_pct)",
            "scale_pct": scale,
            "production_validated": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    kronos_repo = Path(args.kronos_repo).expanduser().resolve()
    if not (kronos_repo / "model").exists():
        raise RuntimeError(f"KRONOS_REPO_INVALID: {kronos_repo}")
    sys.path.insert(0, str(kronos_repo))

    import torch
    from model import Kronos, KronosPredictor, KronosTokenizer

    config = MODEL_CONFIGS[args.model]
    codec = KronosTokenizer.from_pretrained(config["codec"])
    model = Kronos.from_pretrained(config["model"])
    codec.eval()
    model.eval()
    predictor = KronosPredictor(model, codec, device=args.device, max_context=config["max_context"])

    horizons = {
        "1h": _run_horizon(
            predictor, torch, input_path=Path(args.input_1h), timeframe="1h",
            lookback=args.lookback_1h, pred_len=args.pred_len_1h,
            sample_count=args.sample_count, temperature=args.temperature, top_p=args.top_p,
        ),
        "4h": _run_horizon(
            predictor, torch, input_path=Path(args.input_4h), timeframe="4h",
            lookback=args.lookback_4h, pred_len=args.pred_len_4h,
            sample_count=args.sample_count, temperature=args.temperature, top_p=args.top_p,
        ),
    }
    payload = {
        "contract_version": "kronos-evidence-v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "asset": "ETH-USD",
        "mode": "SHADOW",
        "model": {
            "name": f"Kronos-{args.model}",
            "hub_model": config["model"],
            "hub_codec": config["codec"],
            "repo_sha": _repo_sha(kronos_repo),
            "device": str(predictor.device),
        },
        "horizons": horizons,
        "guardrails": {
            "decision_active": False,
            "probability_generated": False,
            "order_execution_allowed": False,
            "sample_directional_agreement_is_probability": False,
        },
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
