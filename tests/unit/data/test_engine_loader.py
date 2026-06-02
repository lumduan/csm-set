"""Tests for the Market Data Engine OHLCV loader."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from csm.adapters.market_data_engine_client import (
    EngineOHLCVBar,
    EngineOHLCVResponse,
    MarketDataEngineError,
)
from csm.config.settings import Settings
from csm.data.engine_loader import MarketDataEngineLoader
from csm.data.exceptions import DataAccessError, EngineReadError


def _settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    public_mode: bool = False,
    source: str = "db",
    base_url: str | None = "http://marketdata.test:8000",
) -> Settings:
    monkeypatch.setenv("CSM_PUBLIC_MODE", "true" if public_mode else "false")
    monkeypatch.setenv("CSM_OHLCV_SOURCE", source)
    monkeypatch.delenv("CSM_MARKET_DATA_ENGINE_BASE_URL", raising=False)
    if base_url is not None:
        monkeypatch.setenv("CSM_MARKET_DATA_ENGINE_BASE_URL", base_url)
    monkeypatch.delenv("CSM_MARKET_DATA_ENGINE_API_KEY", raising=False)
    return Settings()


def _response(
    *, symbol: str = "SET:PTT", adjusted: bool = False, n: int = 2
) -> EngineOHLCVResponse:
    bars = [
        EngineOHLCVBar(
            ts=datetime(2026, 5, 27 + i, tzinfo=UTC),
            open=Decimal("10.0"),
            high=Decimal("11.0"),
            low=Decimal("9.0"),
            close=Decimal("10.5"),
            volume=Decimal("1000"),
            open_interest=None,
        )
        for i in range(n)
    ]
    return EngineOHLCVResponse(symbol=symbol, timeframe="1d", adjusted=adjusted, bars=bars)


class _FakeClient:
    """Stand-in for MarketDataEngineClient capturing calls and returning canned data."""

    instances: list[_FakeClient] = []
    fail_symbols: set[str] = set()
    response_adjusted: bool = False

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.calls: list[dict[str, object]] = []
        type(self).instances.append(self)

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        *,
        adjusted: bool,
        limit: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> EngineOHLCVResponse:
        self.calls.append(
            {"symbol": symbol, "timeframe": timeframe, "adjusted": adjusted, "limit": limit}
        )
        if symbol in type(self).fail_symbols:
            raise MarketDataEngineError(f"boom for {symbol}")
        return _response(symbol=symbol, adjusted=adjusted)


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    _FakeClient.instances = []
    _FakeClient.fail_symbols = set()


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("csm.data.engine_loader.MarketDataEngineClient", _FakeClient)


class TestResolve:
    def test_daily_dividends_routes_to_adjusted(self) -> None:
        tf, adjusted = MarketDataEngineLoader._resolve("1D", "dividends", "dividends")
        assert tf == "1d"
        assert adjusted is True

    def test_splits_routes_to_raw(self) -> None:
        tf, adjusted = MarketDataEngineLoader._resolve("1D", "splits", "dividends")
        assert tf == "1d"
        assert adjusted is False

    def test_falls_back_to_default_adjustment(self) -> None:
        _, adjusted = MarketDataEngineLoader._resolve("1d", None, "splits")
        assert adjusted is False

    def test_unsupported_interval_raises(self) -> None:
        with pytest.raises(ValueError, match="does not support"):
            MarketDataEngineLoader._resolve("1W", "dividends", "dividends")

    def test_unknown_adjustment_raises(self) -> None:
        with pytest.raises(ValueError):
            MarketDataEngineLoader._resolve("1d", "bogus", "dividends")


class TestResponseToFrame:
    def test_shape_dtypes_and_tz(self) -> None:
        frame = MarketDataEngineLoader._response_to_frame(_response(n=2))
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index.name == "datetime"
        assert str(frame.index.tz) == "Asia/Bangkok"
        assert frame.index.is_monotonic_increasing
        for col in frame.columns:
            assert frame[col].dtype == "float64"

    def test_empty_response_is_zero_row_frame(self) -> None:
        empty = EngineOHLCVResponse(symbol="X", timeframe="1d", adjusted=False, bars=[])
        frame = MarketDataEngineLoader._response_to_frame(empty)
        assert frame.empty
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index.name == "datetime"
        assert str(frame.index.tz) == "Asia/Bangkok"


class TestFetch:
    async def test_public_mode_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = _settings(monkeypatch, public_mode=True, source="parquet")
        loader = MarketDataEngineLoader(settings=settings)
        with pytest.raises(DataAccessError):
            await loader.fetch("SET:PTT", "1D", 600)

    async def test_returns_canonical_frame(
        self, monkeypatch: pytest.MonkeyPatch, patched_client: None
    ) -> None:
        settings = _settings(monkeypatch)
        loader = MarketDataEngineLoader(settings=settings)
        frame = await loader.fetch("SET:PTT", "1D", 600)
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert str(frame.index.tz) == "Asia/Bangkok"
        # bars=600 maps to the engine limit on the single call.
        assert _FakeClient.instances[0].calls[0]["limit"] == 600

    async def test_dividends_uses_adjusted_endpoint(
        self, monkeypatch: pytest.MonkeyPatch, patched_client: None
    ) -> None:
        settings = _settings(monkeypatch)
        loader = MarketDataEngineLoader(settings=settings)
        await loader.fetch("SET:PTT", "1D", 10, adjustment="dividends")
        assert _FakeClient.instances[0].calls[0]["adjusted"] is True

    async def test_missing_base_url_raises_engine_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # source=parquet so the settings validator does not require a base URL.
        settings = _settings(monkeypatch, source="parquet", base_url=None)
        loader = MarketDataEngineLoader(settings=settings)
        with pytest.raises(EngineReadError, match="not configured"):
            await loader.fetch("SET:PTT", "1D", 10)


class TestFetchBatch:
    async def test_public_mode_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = _settings(monkeypatch, public_mode=True, source="parquet")
        loader = MarketDataEngineLoader(settings=settings)
        with pytest.raises(DataAccessError):
            await loader.fetch_batch(["A", "B"], "1D", 10)

    async def test_returns_all_on_success(
        self, monkeypatch: pytest.MonkeyPatch, patched_client: None
    ) -> None:
        settings = _settings(monkeypatch)
        loader = MarketDataEngineLoader(settings=settings)
        result = await loader.fetch_batch(["SET:A", "SET:B"], "1D", 10)
        assert set(result) == {"SET:A", "SET:B"}

    async def test_per_symbol_failure_is_omitted(
        self, monkeypatch: pytest.MonkeyPatch, patched_client: None
    ) -> None:
        _FakeClient.fail_symbols = {"SET:B"}
        settings = _settings(monkeypatch)
        loader = MarketDataEngineLoader(settings=settings)
        result = await loader.fetch_batch(["SET:A", "SET:B"], "1D", 10)
        assert set(result) == {"SET:A"}
