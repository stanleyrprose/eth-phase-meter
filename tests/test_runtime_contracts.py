from unittest.mock import Mock, patch

from scripts.validate_runtime_contracts import _coinmetrics_recent_contract


@patch("scripts.validate_runtime_contracts.requests.get")
def test_coinmetrics_contract_allows_asynchronous_recent_metrics(get):
    response = Mock(ok=True, status_code=200)
    response.json.return_value = {
        "data": [
            {
                "time": "2026-09-11T00:00:00.000000000Z",
                "CapMVRVCur": "1.11",
                "FlowInExNtv": "337570.8",
                "FlowOutExNtv": "339393.4",
            },
            {
                "time": "2026-09-12T00:00:00.000000000Z",
                "CapMVRVCur": None,
                "FlowInExNtv": "91579.3",
                "FlowOutExNtv": "119834.6",
            },
        ]
    }
    get.return_value = response

    ok, detail = _coinmetrics_recent_contract()

    assert ok is True
    assert detail["latest_row"] == "2026-09-12T00:00:00.000000000Z"
    assert detail["mvrv_observed_at"] == "2026-09-11T00:00:00.000000000Z"
    assert detail["exchange_flow_observed_at"] == "2026-09-12T00:00:00.000000000Z"


@patch("scripts.validate_runtime_contracts.requests.get")
def test_coinmetrics_contract_still_fails_when_recent_mvrv_is_absent(get):
    response = Mock(ok=True, status_code=200)
    response.json.return_value = {
        "data": [
            {
                "time": "2026-09-12T00:00:00.000000000Z",
                "CapMVRVCur": None,
                "FlowInExNtv": "91579.3",
                "FlowOutExNtv": "119834.6",
            }
        ]
    }
    get.return_value = response

    ok, detail = _coinmetrics_recent_contract()

    assert ok is False
    assert detail["mvrv_observed_at"] is None
    assert detail["exchange_flow_observed_at"] == "2026-09-12T00:00:00.000000000Z"
