"""Unit tests for :mod:`csm.adapters.market_data_engine_client`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from csm.adapters.market_data_engine_client import (
    OHLCV_ADJUSTED_PATH,
    OHLCV_PATH,
    MarketDataEngineClient,
    MarketDataEngineError,
)

BASE_URL: str = "http://marketdata.test"
API_KEY: str = "engine-read-key"


def _ohlcv_body(*, symbol: str = "SET:PTT", adjusted: bool = False, bars: int = 1) -> str:
    """Build a realistic engine OHLCV response body (Decimal-as-string wire form)."""
    rows = [
        {
            "ts": "2026-05-29T00:00:00Z",
            "open": "10.000000",
            "high": "11.000000",
            "low": "9.000000",
            "close": "10.500000",
            "volume": "1000.0000",
            "open_interest": "42.0000",
        }
        for _ in range(bars)
    ]
    return json.dumps({"symbol": symbol, "timeframe": "1d", "adjusted": adjusted, "bars": rows})


def _empty_body(*, adjusted: bool = False) -> str:
    return json.dumps({"symbol": "SET:PTT", "timeframe": "1d", "adjusted": adjusted, "bars": []})


class _ResponseSequencer:
    """httpx.MockTransport handler that yields a queued response per call."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses: list[httpx.Response] = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("MockTransport received an unexpected extra request")
        return self._responses.pop(0)


class TestConstructor:
    def test_rejects_empty_base_url(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            MarketDataEngineClient(base_url="")

    def test_rejects_zero_max_attempts(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            MarketDataEngineClient(base_url=BASE_URL, max_attempts=0)

    def test_api_key_optional(self) -> None:
        client = MarketDataEngineClient(base_url=BASE_URL)
        assert client is not None


class TestGetOHLCV:
    @pytest.mark.asyncio
    async def test_happy_path_parses_decimal_and_ts(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(200, text=_ohlcv_body())])
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, api_key=API_KEY, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            resp = await client.get_ohlcv("SET:PTT", "1d", adjusted=False, limit=5000)

        assert resp.symbol == "SET:PTT"
        assert resp.adjusted is False
        bar = resp.bars[0]
        assert bar.open == Decimal("10.000000")
        assert bar.volume == Decimal("1000.0000")
        assert bar.open_interest == Decimal("42.0000")
        assert bar.ts == datetime(2026, 5, 29, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_raw_endpoint_path_and_params(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(200, text=_ohlcv_body())])
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, api_key=API_KEY, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            await client.get_ohlcv("SET:PTT", "1d", adjusted=False, limit=600)

        sent = sequencer.requests[0]
        assert sent.method == "GET"
        assert sent.url.path == OHLCV_PATH
        assert sent.url.params["symbol"] == "SET:PTT"
        assert sent.url.params["timeframe"] == "1d"
        assert sent.url.params["limit"] == "600"
        assert sent.headers["X-API-Key"] == API_KEY

    @pytest.mark.asyncio
    async def test_adjusted_routes_to_adjusted_endpoint(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(200, text=_ohlcv_body(adjusted=True))])
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, api_key=API_KEY, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            resp = await client.get_ohlcv("SET:PTT", "1d", adjusted=True, limit=5000)

        assert resp.adjusted is True
        assert sequencer.requests[0].url.path == OHLCV_ADJUSTED_PATH

    @pytest.mark.asyncio
    async def test_start_end_params_isoformatted(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(200, text=_ohlcv_body())])
        transport = httpx.MockTransport(sequencer)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 6, 1, tzinfo=UTC)
        async with MarketDataEngineClient(
            base_url=BASE_URL, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            await client.get_ohlcv("X", "1d", adjusted=False, limit=10, start=start, end=end)

        params = sequencer.requests[0].url.params
        assert params["start"] == start.isoformat()
        assert params["end"] == end.isoformat()

    @pytest.mark.asyncio
    async def test_no_api_key_omits_header(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(200, text=_ohlcv_body())])
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            await client.get_ohlcv("X", "1d", adjusted=False, limit=10)

        assert "X-API-Key" not in sequencer.requests[0].headers

    @pytest.mark.asyncio
    async def test_empty_bars_is_ok(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(200, text=_empty_body())])
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            resp = await client.get_ohlcv("X", "1d", adjusted=False, limit=10)

        assert resp.bars == []

    @pytest.mark.asyncio
    async def test_401_is_terminal_no_retry(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(401, text="invalid key")])
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            with pytest.raises(MarketDataEngineError, match="401"):
                await client.get_ohlcv("X", "1d", adjusted=False, limit=10)
        assert len(sequencer.requests) == 1

    @pytest.mark.asyncio
    async def test_422_is_terminal_no_retry(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(422, text="bad params")])
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            with pytest.raises(MarketDataEngineError, match="422"):
                await client.get_ohlcv("X", "1d", adjusted=False, limit=10)
        assert len(sequencer.requests) == 1

    @pytest.mark.asyncio
    async def test_retries_on_5xx_then_succeeds(self) -> None:
        sequencer = _ResponseSequencer(
            [
                httpx.Response(503, text="overloaded"),
                httpx.Response(503, text="overloaded"),
                httpx.Response(200, text=_ohlcv_body()),
            ]
        )
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            resp = await client.get_ohlcv("X", "1d", adjusted=False, limit=10)
        assert len(resp.bars) == 1
        assert len(sequencer.requests) == 3

    @pytest.mark.asyncio
    async def test_5xx_exhausts_attempts_then_raises(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(500, text="boom") for _ in range(3)])
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            with pytest.raises(MarketDataEngineError, match="after 3 attempts"):
                await client.get_ohlcv("X", "1d", adjusted=False, limit=10)
        assert len(sequencer.requests) == 3

    @pytest.mark.asyncio
    async def test_transport_error_is_retried(self) -> None:
        attempts: list[httpx.Request] = []

        def _flaky(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            if len(attempts) < 2:
                raise httpx.ConnectError("dns blip")
            return httpx.Response(200, text=_ohlcv_body())

        transport = httpx.MockTransport(_flaky)
        async with MarketDataEngineClient(
            base_url=BASE_URL, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            resp = await client.get_ohlcv("X", "1d", adjusted=False, limit=10)
        assert len(resp.bars) == 1
        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_unparseable_body_raises(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(200, text="not json")])
        transport = httpx.MockTransport(sequencer)
        async with MarketDataEngineClient(
            base_url=BASE_URL, transport=transport, backoff_seconds=(0.0,)
        ) as client:
            with pytest.raises(MarketDataEngineError, match="unparseable"):
                await client.get_ohlcv("X", "1d", adjusted=False, limit=10)
