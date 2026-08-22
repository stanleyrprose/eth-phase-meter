from __future__ import annotations
import os
import time
import requests

DUNE_EXECUTE_URL = "https://api.dune.com/api/v1/sql/execute"
DUNE_RESULT_URL = "https://api.dune.com/api/v1/execution/{execution_id}/results"

DUNE_ETH_STATE_SQL = """
WITH eth_cex AS (
  SELECT
    COALESCE(SUM(CASE
      WHEN flow_type = 'deposit' THEN amount
      WHEN flow_type = 'withdrawal' THEN -amount
      ELSE 0 END), 0) AS exchange_netflow_eth
  FROM cex.flows
  WHERE blockchain = 'ethereum'
    AND token_symbol = 'ETH'
    AND block_time >= NOW() - INTERVAL '1' DAY
),
stablecoin_cex AS (
  SELECT
    COALESCE(SUM(CASE
      WHEN flow_type = 'deposit' THEN amount_usd
      WHEN flow_type = 'withdrawal' THEN -amount_usd
      ELSE 0 END), 0) AS stablecoin_flow_usd
  FROM cex.flows
  WHERE blockchain = 'ethereum'
    AND token_symbol IN ('USDT', 'USDC', 'DAI')
    AND block_time >= NOW() - INTERVAL '1' DAY
),
staking AS (
  SELECT
    COALESCE(SUM(amount_staked), 0)
      - COALESCE(SUM(amount_full_withdrawn), 0)
      - COALESCE(SUM(amount_partial_withdrawn), 0) AS staking_netflow_eth
  FROM staking_ethereum.flows
  WHERE block_time >= NOW() - INTERVAL '1' DAY
)
SELECT
  exchange_netflow_eth,
  stablecoin_flow_usd,
  staking_netflow_eth
FROM eth_cex
CROSS JOIN stablecoin_cex
CROSS JOIN staking
""".strip()


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


def _safe_http_error(resp: requests.Response, prefix: str) -> dict:
    message = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                message = str(err.get("message") or err.get("type") or "")
            else:
                message = str(body.get("message") or body.get("error") or "")
    except Exception:
        message = (resp.text or "")[:300]
    return {
        "_error": prefix,
        "http_status": resp.status_code,
        "message": message[:300],
    }


def _dune_execute(sql: str, timeout_seconds: int = 50) -> dict:
    api_key = os.getenv("DUNE_API_KEY")
    if not api_key:
        return {"_error": "DUNE_API_KEY_NOT_CONFIGURED"}
    headers = {
        "X-Dune-Api-Key": api_key,
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            DUNE_EXECUTE_URL,
            headers=headers,
            json={"sql": sql, "performance": "small"},
            timeout=20,
        )
        if not r.ok:
            return _safe_http_error(r, "DUNE_EXECUTE_HTTP_ERROR")
        execution_id = r.json().get("execution_id")
        if not execution_id:
            return {"_error": "DUNE_EXECUTION_ID_MISSING"}

        deadline = time.monotonic() + timeout_seconds
        result_url = DUNE_RESULT_URL.format(execution_id=execution_id)
        while time.monotonic() < deadline:
            rr = requests.get(result_url, headers=headers, timeout=20)
            if not rr.ok:
                err = _safe_http_error(rr, "DUNE_RESULT_HTTP_ERROR")
                err["execution_id"] = execution_id
                return err
            body = rr.json()
            state = body.get("state")
            if state == "QUERY_STATE_COMPLETED":
                rows = ((body.get("result") or {}).get("rows") or [])
                if not rows:
                    return {"_error": "DUNE_EMPTY_RESULT", "execution_id": execution_id}
                return {
                    **rows[0],
                    "_source": "Dune curated tables",
                    "execution_id": execution_id,
                }
            if state in {"QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED"}:
                err = body.get("error") or {}
                return {
                    "_error": "DUNE_QUERY_FAILED",
                    "message": err.get("message") if isinstance(err, dict) else str(err),
                    "execution_id": execution_id,
                }
            time.sleep(2)
        return {"_error": "DUNE_QUERY_TIMEOUT", "execution_id": execution_id}
    except requests.RequestException as exc:
        return {"_error": type(exc).__name__, "message": str(exc)[:300]}
    except Exception as exc:
        return {"_error": type(exc).__name__, "message": str(exc)[:300]}


def _dune_external_state() -> dict:
    row = _dune_execute(DUNE_ETH_STATE_SQL)
    if row.get("_error"):
        # Safe diagnostics only: never log API keys or authorization headers.
        print(
            "DUNE_STATE_ERROR",
            {
                "error": row.get("_error"),
                "http_status": row.get("http_status"),
                "message": row.get("message"),
                "execution_id": row.get("execution_id"),
            },
        )
        err = {
            "_error": row.get("_error"),
            "_source": "Dune",
            "message": row.get("message"),
            "http_status": row.get("http_status"),
        }
        return {"valuation": {}, "capital_flow": dict(err), "structural": dict(err)}

    capital_flow = {
        "exchange_netflow_eth": row.get("exchange_netflow_eth"),
        "stablecoin_flow_usd": row.get("stablecoin_flow_usd"),
        "_source": "Dune cex.flows (24h; deposit-positive, withdrawal-negative)",
    }
    structural = {
        "staking_netflow_eth": row.get("staking_netflow_eth"),
        "_source": "Dune staking_ethereum.flows (24h)",
    }
    print(
        "DUNE_STATE_OK",
        {
            "exchange_netflow_eth": capital_flow.get("exchange_netflow_eth"),
            "stablecoin_flow_usd": capital_flow.get("stablecoin_flow_usd"),
            "staking_netflow_eth": structural.get("staking_netflow_eth"),
            "execution_id": row.get("execution_id"),
        },
    )
    return {
        # MVRV/NUPL/realized-value data are intentionally not proxied here.
        "valuation": {},
        "capital_flow": capital_flow,
        "structural": structural,
    }


def collect_external_state() -> dict:
    """Collect ETH-native state.

    Explicit ETH_* adapter URLs take precedence for backward compatibility.
    If none are configured and DUNE_API_KEY exists, use Dune curated tables.
    Missing metrics stay missing; no zero-value imputation is performed.
    """
    explicit = any(
        os.getenv(name)
        for name in ("ETH_VALUATION_API_URL", "ETH_FLOW_API_URL", "ETH_STRUCTURAL_API_URL")
    )
    if explicit:
        return {
            "valuation": _fetch_json("ETH_VALUATION_API_URL", "ETH_VALUATION_API_TOKEN"),
            "capital_flow": _fetch_json("ETH_FLOW_API_URL", "ETH_FLOW_API_TOKEN"),
            "structural": _fetch_json("ETH_STRUCTURAL_API_URL", "ETH_STRUCTURAL_API_TOKEN"),
        }
    if os.getenv("DUNE_API_KEY"):
        return _dune_external_state()
    return {"valuation": {}, "capital_flow": {}, "structural": {}}
