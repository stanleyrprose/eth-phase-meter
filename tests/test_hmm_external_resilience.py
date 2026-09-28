from __future__ import annotations

import json

import pandas as pd
import pytest
import requests

import eth_trend_v3.hmm_bootstrap as bootstrap
import eth_trend_v3.hmm_ablation as ablation


def test_retry_exhaustion_is_classified_as_external_data_unavailable(monkeypatch):
    class Session:
        def get(self, *args, **kwargs):
            raise requests.exceptions.RetryError("too many 503 responses")

    monkeypatch.setattr(bootstrap, "_http_session", lambda: Session())
    with pytest.raises(bootstrap.ExternalDataUnavailable) as exc:
        bootstrap.fetch_deribit_4h_history(days=1)
    assert exc.value.source == "Deribit"


def test_cloudflare_525_is_classified_as_external_data_unavailable(monkeypatch):
    class Session:
        def get(self, *args, **kwargs):
            response = requests.Response()
            response.status_code = 525
            response.url = "https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
            return response

    monkeypatch.setattr(bootstrap, "_http_session", lambda: Session())
    with pytest.raises(bootstrap.ExternalDataUnavailable) as exc:
        bootstrap.fetch_deribit_4h_history(days=1)
    assert exc.value.status_code == 525


def test_resilient_bootstrap_writes_fail_closed_unavailable_artifact(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise bootstrap.ExternalDataUnavailable(
            "Deribit",
            "Deribit history returned retryable HTTP 503",
            status_code=503,
        )

    monkeypatch.setattr(bootstrap, "run", fail)
    report = bootstrap.run_resilient(days=365, out_dir=str(tmp_path))

    assert report["status"] == "EXTERNAL_DATA_UNAVAILABLE"
    assert report["promotion_allowed"] is False
    assert report["preferred_descriptive_variant"] is None
    assert report["status_code"] == 503
    assert not (tmp_path / "features.csv").exists()

    persisted = json.loads((tmp_path / "report.json").read_text())
    assert persisted["status"] == "EXTERNAL_DATA_UNAVAILABLE"
    assert "No HMM candidate" in (tmp_path / "report.md").read_text()


def test_resilient_bootstrap_does_not_mask_internal_errors(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise ValueError("model contract bug")

    monkeypatch.setattr(bootstrap, "run", fail)
    with pytest.raises(ValueError, match="model contract bug"):
        bootstrap.run_resilient(days=365, out_dir=str(tmp_path))


def test_ablation_reuses_bootstrap_features_without_second_network_fetch(monkeypatch, tmp_path):
    source = tmp_path / "features.csv"
    pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=5, freq="4h", tz="UTC"),
            "log_return": [0.01, -0.01, 0.02, -0.02, 0.01],
            "log_return_24h": [0.02, 0.01, 0.03, -0.01, 0.0],
            "realized_volatility": [0.1] * 5,
            "log_volume_change": [0.0] * 5,
        }
    ).to_csv(source, index=False)

    monkeypatch.setattr(
        ablation,
        "fetch_deribit_4h_history",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network fetch must not occur")),
    )
    monkeypatch.setattr(
        ablation,
        "run_ablation",
        lambda features: {
            "schema_version": "hmm-forecast-ablation-v4",
            "method": "fixture",
            "horizons": {
                "3d": {"available": False, "reason": "fixture"},
                "7d": {"available": False, "reason": "fixture"},
                "30d": {"available": False, "reason": "fixture"},
            },
            "promotion_allowed": False,
        },
    )

    out = tmp_path / "out"
    report = ablation.run(features_path=str(source), out_dir=str(out))
    assert report["history_source"] == "bootstrap_features_artifact"
    assert json.loads((out / "report.json").read_text())["history_source"] == "bootstrap_features_artifact"
