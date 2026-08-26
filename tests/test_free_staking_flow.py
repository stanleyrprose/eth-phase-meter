from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import eth_phase_meter as core
from eth_trend_v3.market_state import build_market_state
from eth_trend_v3.structural_flow import enrich_staking_netflow

UTC = timezone.utc


def _pit(observed_at: datetime, deposit_balance: float, withdrawn_total: float) -> dict:
    return {
        "observed_at": observed_at.isoformat(),
        "github_event": "schedule",
        "schedule_nominal_time": observed_at.replace(minute=15, second=0, microsecond=0).isoformat(),
        "metric_value": {"timeframe": "4h", "price": 2500.0},
        "raw_payload": {
            "structural": {
                "staking_deposit_contract_balance_eth": deposit_balance,
                "beacon_withdrawn_total_eth": withdrawn_total,
                "staking_counters_observed_at": observed_at.isoformat(),
            }
        },
    }


def test_staking_flow_waits_for_real_24h_pit_baseline():
    now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    raw = {
        "structural": {
            "staking_deposit_contract_balance_eth": 40_000_000.0,
            "beacon_withdrawn_total_eth": 7_620_000.0,
            "staking_counters_observed_at": now.isoformat(),
        }
    }
    enrich_staking_netflow(raw, [_pit(now - timedelta(hours=4), 39_999_000.0, 7_619_500.0)])
    assert raw["structural"]["_staking_flow_status"] == "WAITING_FOR_24H_BASELINE"
    assert "staking_netflow_eth" not in raw["structural"]


def test_staking_flow_uses_prior_canonical_pit_and_adds_independent_structural_vote():
    now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    raw = {
        "structural": {
            "net_issuance_eth": 3000.0,
            "exchange_balance_change_pct": -0.2,
            "staking_deposit_contract_balance_eth": 40_003_200.0,
            "beacon_withdrawn_total_eth": 7_620_500.0,
            "staking_counters_observed_at": now.isoformat(),
        }
    }
    history = [
        _pit(now - timedelta(hours=28), 39_998_000.0, 7_619_800.0),
        _pit(now - timedelta(hours=24), 40_000_000.0, 7_620_000.0),
    ]
    enrich_staking_netflow(raw, history)
    structural = raw["structural"]
    assert structural["staking_deposits_24h_eth"] == 3200.0
    assert structural["beacon_withdrawals_24h_eth"] == 500.0
    assert structural["staking_netflow_eth"] == 2700.0
    assert structural["staking_netflow_source"] == "Etherscan PIT delta"
    assert structural["_staking_flow_status"] == "READY"

    result = SimpleNamespace(
        quality={"families": {"Technical": {"nominal": 40, "active": 40, "coverage": 100, "contribution": 0}}},
        crowding=10,
        volatility=20,
    )
    state = build_market_state({"valuation": {}, "capital_flow": {}, "structural": structural}, result)
    assert state["dimensions"]["structural_supply"]["coverage"] == 75.0


def test_staking_flow_fails_closed_on_counter_regression():
    now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    raw = {
        "structural": {
            "staking_deposit_contract_balance_eth": 39_999_000.0,
            "beacon_withdrawn_total_eth": 7_619_000.0,
            "staking_counters_observed_at": now.isoformat(),
        }
    }
    enrich_staking_netflow(raw, [_pit(now - timedelta(hours=24), 40_000_000.0, 7_620_000.0)])
    assert raw["structural"]["_staking_flow_status"] == "COUNTER_REGRESSION"
    assert "staking_netflow_eth" not in raw["structural"]


@patch.object(core, "ETHERSCAN_API_KEY", "test-key")
@patch.object(core.SESSION, "get")
def test_etherscan_supply_fields_are_semantically_mapped(get):
    gas = Mock()
    gas.raise_for_status.return_value = None
    gas.json.return_value = {"status": "1", "result": {"SafeGasPrice": "1", "ProposeGasPrice": "2", "FastGasPrice": "3"}}

    supply = Mock()
    supply.raise_for_status.return_value = None
    supply.json.return_value = {
        "status": "1",
        "result": {
            "EthSupply": "122000000000000000000000000",
            "Eth2Staking": "2940000000000000000000000",
            "BurntFees": "4600000000000000000000000",
            "WithdrawnTotal": "7600000000000000000000000",
        },
    }

    balance = Mock()
    balance.raise_for_status.return_value = None
    balance.json.return_value = {"status": "1", "result": "40000000000000000000000000"}
    get.side_effect = [gas, supply, balance]

    result = core.fetch_etherscan_onchain()
    assert result["eth2_staking_rewards"] == 2_940_000.0
    assert result["beacon_withdrawn_total_eth"] == 7_600_000.0
    assert result["staking_deposit_contract_balance_eth"] == 40_000_000.0
    assert "staking_ratio" not in result


def test_explicit_structural_adapter_keeps_precedence_over_free_baseline():
    now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    raw = {
        "structural": {
            "staking_netflow_eth": 999.0,
            "_source": "explicit adapter: ETH_STRUCTURAL_API_URL",
            "staking_deposit_contract_balance_eth": 40_003_200.0,
            "beacon_withdrawn_total_eth": 7_620_500.0,
            "staking_counters_observed_at": now.isoformat(),
        }
    }
    enrich_staking_netflow(raw, [_pit(now - timedelta(hours=24), 40_000_000.0, 7_620_000.0)])
    assert raw["structural"]["staking_netflow_eth"] == 999.0
    assert raw["structural"]["staking_netflow_parallel_etherscan_eth"] == 2700.0
