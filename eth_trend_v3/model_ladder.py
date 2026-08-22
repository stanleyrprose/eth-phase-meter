"""Deprecated compatibility wrapper.

The canonical model ladder and promotion logic live in ``eth_trend_v3.forecast``.
This module remains only to avoid breaking external imports from earlier V3 work.
"""
from __future__ import annotations

from .forecast import MODEL_LADDER, evaluate_model_ladder


def select_live_model(rows: list[dict], current: dict | None = None) -> dict:
    selected, candidates = evaluate_model_ladder(rows)
    return {
        "selected": selected,
        "candidates": candidates,
        "note": "Canonical selection is validation-only here; live probability is produced by forecast.fit_live_probability.",
    }


__all__ = ["MODEL_LADDER", "select_live_model"]
