import eth_phase_meter as core


def test_binance_proxy_is_scoped_to_binance_hosts(monkeypatch):
    proxy = "socks5h://127.0.0.1:19080"
    monkeypatch.setattr(core, "BINANCE_PROXY_URL", proxy)

    expected = {"http": proxy, "https": proxy}
    assert core._binance_proxy_for("https://api.binance.com/api/v3/ping") == expected
    assert core._binance_proxy_for("https://fapi.binance.com/fapi/v1/ping") == expected
    assert core._binance_proxy_for("https://www.deribit.com/api/v2/public/test") is None


def test_binance_proxy_is_disabled_without_configuration(monkeypatch):
    monkeypatch.setattr(core, "BINANCE_PROXY_URL", "")
    assert core._binance_proxy_for("https://fapi.binance.com/fapi/v1/ping") is None
