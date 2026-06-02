"""HTTP client for the API Gateway's daily-report ingestion contract.

Used by the post-refresh hook to deliver the report payload built by
:mod:`csm.adapters.payload` to ``POST /api/v1/ingest/daily-report``. The
client owns one shared :class:`httpx.AsyncClient`, retries on transient
5xx responses with exponential backoff, surfaces 4xx as terminal errors,
and supports a custom transport for testability.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS: float = 15.0
DEFAULT_MAX_ATTEMPTS: int = 3
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
INGEST_PATH: str = "/api/v1/ingest/daily-report"


class GatewayWriteError(Exception):
    """Raised when the daily-report POST fails after all retry attempts."""


class GatewayClient:
    """Async HTTP client that POSTs daily reports to the gateway.

    Args:
        base_url: Gateway base URL (without the path), e.g.
            ``http://quant-api-gateway:8000``.
        api_key: Shared ``INTERNAL_API_KEY`` sent as ``X-API-Key``.
        timeout: Per-request timeout in seconds.
        max_attempts: Total POST attempts (initial + retries) on 5xx.
        backoff_seconds: Sequence of sleep durations between retries.
            Indexed by ``attempt_index`` (0-based); clamped to the last
            value when more attempts are configured than backoff entries.
        transport: Optional custom :class:`httpx.AsyncBaseTransport`
            for tests (e.g. :class:`httpx.MockTransport`).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seconds: tuple[float, ...] = DEFAULT_BACKOFF_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        self._base_url: str = base_url.rstrip("/")
        self._api_key: str = api_key
        self._max_attempts: int = max_attempts
        self._backoff: tuple[float, ...] = backoff_seconds or (0.0,)
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client. Idempotent."""
        await self._client.aclose()

    async def __aenter__(self) -> GatewayClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def post_daily_report(self, payload: dict[str, Any]) -> None:
        """POST the payload to the gateway. Retries 5xx; raises on 4xx or final failure.

        Args:
            payload: The dict built by
                :func:`csm.adapters.payload.build_ingestion_payload`.

        Raises:
            GatewayWriteError: If all attempts fail or a 4xx is returned.
        """
        headers: dict[str, str] = {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }
        last_exc: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.post(INGEST_PATH, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "gateway daily-report POST transport error (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_attempts,
                    exc,
                )
            else:
                if response.is_success:
                    logger.info(
                        "gateway daily-report POST ok status=%d strategy_id=%s",
                        response.status_code,
                        payload.get("strategy_metadata", {}).get("id", "?"),
                    )
                    return
                if 400 <= response.status_code < 500:
                    body = response.text[:500]
                    raise GatewayWriteError(
                        f"gateway rejected daily-report with {response.status_code}: {body}"
                    )
                last_exc = GatewayWriteError(
                    f"gateway returned {response.status_code}: {response.text[:200]}"
                )
                logger.warning(
                    "gateway daily-report POST 5xx (attempt %d/%d): %d %s",
                    attempt + 1,
                    self._max_attempts,
                    response.status_code,
                    response.text[:200],
                )

            if attempt + 1 < self._max_attempts:
                sleep_for = self._backoff[min(attempt, len(self._backoff) - 1)]
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)

        raise GatewayWriteError(
            f"gateway daily-report POST failed after {self._max_attempts} attempts"
        ) from last_exc


__all__: list[str] = ["GatewayClient", "GatewayWriteError", "INGEST_PATH"]
