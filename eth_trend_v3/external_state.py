from __future__ import annotations
import os
import time
import requests

COINMETRICS_COMMUNITY_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
DEFILLAMA_ETH_STABLECOIN_URL = "https://stablecoins.llama.fi/stablecoincharts/Ethereum"

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


def _float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _merge_dimension(base: dict, enrichment: dict, provider_name: str) -> dict:
    """Merge non-metadata metrics while preserving provenance and optional provider errors."""
    out = dict(base or {})
    enrichment = enrichment or {}
    err = enrichment.get("_error")
    if err:
        provider_errors = dict(out.get("_provider_errors") or {})
        provider_errors[provider_name] = {
            "error": err,
            "http_status": enrichment.get("http_status"),
            "message": enrichment.get("message"),
        }
        out["_provider_errors"] = provider_errors
        if not any(not str(key).startswith("_") for key in out):
            out["_error"] = err
        return out

    for key, value in enrichment.items():
        if str(key).startswith("_"):
            continue
        if value is not None:
            out[key] = value
    sources = [x for x in (out.get("_source"), enrichment.get("_source")) if x]
    if sources:
        out["_source"] = " + ".join(dict.fromkeys(sources))
    observed = [x for x in (out.get("_observed_at"), enrichment.get("_observed_at")) if x]
    if observed:
        out["_observed_at"] = max(observed)
    out.pop("_error", None)
    return out


def _coinmetrics_community_state() -> dict:
    """Free daily ETH valuation/supply metrics; no API key required."""
    try:
        response = requests.get(
            COINMETRICS_COMMUNITY_URL,
            params={
                "assets": "eth",
                "metrics": "CapMVRVCur,SplyExNtv,SplyCur",
                "frequency": "1d",
                "page_size": 3,
                "paging_from": "end",
            },
            timeout=20,
        )
        if not response.ok:
            err = _safe_http_error(response, "COINMETRICS_HTTP_ERROR")
            return {"valuation": dict(err), "structural": dict(err)}
        rows = response.json().get("data") or []
        if not rows:
            err = {"_error": "COINMETRICS_EMPTY_RESULT", "_source": "Coin Metrics Community"}
            return {"valuation": dict(err), "structural": dict(err)}
        rows = sorted(rows, key=lambda row: str(row.get("time") or ""))
        latest = rows[-1]
        previous = rows[-2] if len(rows) >= 2 else {}
        observed_at = latest.get("time")

        valuation = {
            "mvrv": _float(latest.get("CapMVRVCur")),
            "_source": "Coin Metrics Community: CapMVRVCur",
            "_observed_at": observed_at,
        }
        valuation = {k: v for k, v in valuation.items() if v is not None}

        supply_now = _float(latest.get("SplyCur"))
        supply_prev = _float(previous.get("SplyCur"))
        exchange_now = _float(latest.get("SplyExNtv"))
        exchange_prev = _float(previous.get("SplyExNtv"))
        structural = {
            "net_issuance_eth": supply_now - supply_prev if supply_now is not None and supply_prev is not None else None,
            "exchange_balance_change_pct": (
                (exchange_now / exchange_prev - 1.0) * 100.0
                if exchange_now is not None and exchange_prev not in (None, 0)
                else None
            ),
            "exchange_balance_eth": exchange_now,
            "_source": "Coin Metrics Community: SplyCur + SplyExNtv",
            "_observed_at": observed_at,
        }
        structural = {k: v for k, v in structural.items() if v is not None}
        return {"valuation": valuation, "structural": structural}
    except requests.RequestException as exc:
        err = {"_error": type(exc).__name__, "message": str(exc)[:300], "_source": "Coin Metrics Community"}
        return {"valuation": dict(err), "structural": dict(err)}
    except Exception as exc:
        err = {"_error": type(exc).__name__, "message": str(exc)[:300], "_source": "Coin Metrics Community"}
        return {"valuation": dict(err), "structural": dict(err)}


def _defillama_stablecoin_state() -> dict:
    """Free Ethereum stablecoin supply change; semantically distinct from CEX stablecoin flow."""
    try:
        response = requests.get(DEFILLAMA_ETH_STABLECOIN_URL, timeout=20)
        if not response.ok:
            return {"capital_flow": _safe_http_error(response, "DEFILLAMA_STABLECOIN_HTTP_ERROR")}
        rows = response.json()
        if not isinstance(rows, list) or len(rows) < 2:
            return {"capital_flow": {"_error": "DEFILLAMA_STABLECOIN_EMPTY_RESULT", "_source": "DefiLlama"}}
        latest, previous = rows[-1], rows[-2]
        current = _float(((latest.get("totalCirculatingUSD") or {}).get("peggedUSD")))
        prior = _float(((previous.get("totalCirculatingUSD") or {}).get("peggedUSD")))
        if current is None or prior is None:
            return {"capital_flow": {"_error": "DEFILLAMA_STABLECOIN_VALUE_MISSING", "_source": "DefiLlama"}}
        return {
            "capital_flow": {
                "stablecoin_supply_change_usd": current - prior,
                "stablecoin_supply_change_pct": ((current / prior) - 1.0) * 100.0 if prior else None,
                "stablecoin_supply_usd": current,
                "_source": "DefiLlama Ethereum stablecoin circulating supply",
                "_observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(latest.get("date")))),
            }
        }
    except requests.RequestException as exc:
        return {"capital_flow": {"_error": type(exc).__name__, "message": str(exc)[:300], "_source": "DefiLlama"}}
    except Exception as exc:
        return {"capital_flow": {"_error": type(exc).__name__, "message": str(exc)[:300], "_source": "DefiLlama"}}


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
    """Collect ETH-native state with explicit adapters > free baseline > optional Dune enrichment.

    Public baseline providers require no credentials:
    - Coin Metrics Community: MVRV, current supply, exchange-held supply.
    - DefiLlama: Ethereum stablecoin circulating-supply change.

    Dune remains optional enrichment for CEX/staking flow semantics. A Dune failure is
    retained as provider diagnostics but does not poison a dimension when an independent
    public metric is available. Missing metrics stay missing; no zero-value imputation.
    """
    cm = _coinmetrics_community_state()
    llama = _defillama_stablecoin_state()
    result = {
        "valuation": dict(cm.get("valuation") or {}),
        "capital_flow": dict(llama.get("capital_flow") or {}),
        "structural": dict(cm.get("structural") or {}),
    }

    if os.getenv("DUNE_API_KEY"):
        dune = _dune_external_state()
        result["capital_flow"] = _merge_dimension(result["capital_flow"], dune.get("capital_flow") or {}, "dune")
        result["structural"] = _merge_dimension(result["structural"], dune.get("structural") or {}, "dune")

    explicit = {
        "valuation": ("ETH_VALUATION_API_URL", "ETH_VALUATION_API_TOKEN"),
        "capital_flow": ("ETH_FLOW_API_URL", "ETH_FLOW_API_TOKEN"),
        "structural": ("ETH_STRUCTURAL_API_URL", "ETH_STRUCTURAL_API_TOKEN"),
    }
    for dimension, (url_env, token_env) in explicit.items():
        if os.getenv(url_env):
            payload = _fetch_json(url_env, token_env)
            if payload and not payload.get("_source"):
                payload["_source"] = f"explicit adapter: {url_env}"
            result[dimension] = payload
    return result
