from __future__ import annotations
import os
import requests

def _fetch_json(url_env: str, token_env: str | None = None) -> dict:
    url = os.getenv(url_env)
    if not url:
        return {}
    headers = {}
    if token_env and os.getenv(token_env):
        headers["Authorization"] = f"Bearer {os.getenv(token_env)}"
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {"data": data}
    except Exception as exc:
        return {"_error": type(exc).__name__}

def collect_external_state() -> dict:
    return {
        "valuation": _fetch_json("ETH_VALUATION_API_URL", "ETH_VALUATION_API_TOKEN"),
        "capital_flow": _fetch_json("ETH_FLOW_API_URL", "ETH_FLOW_API_TOKEN"),
        "structural": _fetch_json("ETH_STRUCTURAL_API_URL", "ETH_STRUCTURAL_API_TOKEN"),
    }
