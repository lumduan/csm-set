"""Unit tests for :mod:`csm.adapters.gateway_client`."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from csm.adapters.gateway_client import (
    INGEST_PATH,
    GatewayClient,
    GatewayWriteError,
)

BASE_URL: str = "http://gateway.test"
API_KEY: str = "secret-test-key"


def _payload(strategy_id: str = "csm-set") -> dict[str, Any]:
    return {"strategy_metadata": {"id": strategy_id, "type": "EQUITY_MOMENTUM"}}


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
            GatewayClient(base_url="", api_key=API_KEY)

    def test_rejects_empty_api_key(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            GatewayClient(base_url=BASE_URL, api_key="")

    def test_rejects_zero_max_attempts(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            GatewayClient(base_url=BASE_URL, api_key=API_KEY, max_attempts=0)


class TestPostDailyReport:
    @pytest.mark.asyncio
    async def test_2xx_is_accepted(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(201)])
        transport = httpx.MockTransport(sequencer)
        async with GatewayClient(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=transport,
            backoff_seconds=(0.0,),
        ) as client:
            await client.post_daily_report(_payload())
        assert len(sequencer.requests) == 1
        sent = sequencer.requests[0]
        assert sent.method == "POST"
        assert sent.url.path == INGEST_PATH
        assert sent.headers["X-API-Key"] == API_KEY
        assert sent.headers["Content-Type"].startswith("application/json")

    @pytest.mark.asyncio
    async def test_retries_on_5xx_then_succeeds(self) -> None:
        sequencer = _ResponseSequencer(
            [
                httpx.Response(503, text="overloaded"),
                httpx.Response(503, text="overloaded"),
                httpx.Response(200, text="ok"),
            ]
        )
        transport = httpx.MockTransport(sequencer)
        async with GatewayClient(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=transport,
            backoff_seconds=(0.0,),
        ) as client:
            await client.post_daily_report(_payload())
        assert len(sequencer.requests) == 3

    @pytest.mark.asyncio
    async def test_5xx_exhausts_attempts_then_raises(self) -> None:
        sequencer = _ResponseSequencer(
            [
                httpx.Response(500, text="boom"),
                httpx.Response(500, text="boom"),
                httpx.Response(500, text="boom"),
            ]
        )
        transport = httpx.MockTransport(sequencer)
        async with GatewayClient(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=transport,
            backoff_seconds=(0.0,),
        ) as client:
            with pytest.raises(GatewayWriteError, match="after 3 attempts"):
                await client.post_daily_report(_payload())
        assert len(sequencer.requests) == 3

    @pytest.mark.asyncio
    async def test_4xx_is_terminal_no_retry(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(401, text="bad key")])
        transport = httpx.MockTransport(sequencer)
        async with GatewayClient(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=transport,
            backoff_seconds=(0.0,),
        ) as client:
            with pytest.raises(GatewayWriteError, match="401"):
                await client.post_daily_report(_payload())
        assert len(sequencer.requests) == 1

    @pytest.mark.asyncio
    async def test_422_is_terminal_no_retry(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(422, text="bad payload")])
        transport = httpx.MockTransport(sequencer)
        async with GatewayClient(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=transport,
            backoff_seconds=(0.0,),
        ) as client:
            with pytest.raises(GatewayWriteError, match="422"):
                await client.post_daily_report(_payload())
        assert len(sequencer.requests) == 1

    @pytest.mark.asyncio
    async def test_transport_error_is_retried(self) -> None:
        attempts: list[httpx.Request] = []

        def _flaky(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            if len(attempts) < 2:
                raise httpx.ConnectError("dns blip")
            return httpx.Response(201)

        transport = httpx.MockTransport(_flaky)
        async with GatewayClient(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=transport,
            backoff_seconds=(0.0,),
        ) as client:
            await client.post_daily_report(_payload())
        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_payload_body_is_json_encoded(self) -> None:
        sequencer = _ResponseSequencer([httpx.Response(201)])
        transport = httpx.MockTransport(sequencer)
        async with GatewayClient(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=transport,
            backoff_seconds=(0.0,),
        ) as client:
            await client.post_daily_report({"foo": "bar", "n": 1})
        body = sequencer.requests[0].read()
        assert b'"foo":"bar"' in body.replace(b" ", b"")
        assert b'"n":1' in body.replace(b" ", b"")
