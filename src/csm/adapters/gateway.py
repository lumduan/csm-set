"""GatewayAdapter — read-only history adapter for ``db_gateway``.

Owns an ``asyncpg`` connection pool and exposes typed read methods returning
frozen Pydantic models. The schemas themselves are owned by the
``quant-infra-db`` stack and are not declared here.

Write-back to ``db_gateway`` now goes through the documented HTTP ingestion
contract (``POST /api/v1/ingest/daily-report``), implemented by
:class:`csm.adapters.gateway_client.GatewayClient`. This adapter retains
only the history-read code path.

Lifecycle:

>>> async with GatewayAdapter(dsn) as gw:  # doctest: +SKIP
...     rows = await gw.read_daily_performance("csm-set")

For best-effort reads, callers wrap each call in their own
``try/except`` and log a warning on failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from csm.adapters.models import DailyPerformanceRow, PortfolioSnapshotRow
from csm.adapters.postgres import _init_connection

logger: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _GatewaySQL:
    """Centralised SQL statements for ``db_gateway``.

    No inline string concatenation in adapter methods — every statement lives
    here and is referenced by attribute. Idempotency clauses are baked into
    each ``INSERT``.
    """

    # ``days`` is a window of CALENDAR DAYS, not a row count — see the note on
    # PostgresAdapter.read_equity_curve. Day-aligned in UTC and inclusive of today;
    # the alignment is spelled out rather than using ``date_trunc('day', now())``,
    # which resolves in the session timezone.
    SELECT_DAILY_PERFORMANCE_RECENT: str = (
        "SELECT time, strategy_id, daily_return, cumulative_return, "
        "total_value, cash_balance, max_drawdown, sharpe_ratio, metadata "
        "FROM daily_performance "
        "WHERE strategy_id = $1 "
        "  AND time >= (date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') "
        "            - make_interval(days => $2::int - 1) "
        "ORDER BY time ASC"
    )
    SELECT_PORTFOLIO_SNAPSHOTS_RECENT: str = (
        "SELECT time, total_portfolio, weighted_return, combined_drawdown, "
        "active_strategies, allocation "
        "FROM portfolio_snapshot "
        "WHERE time >= (date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') "
        "          - make_interval(days => $1::int - 1) "
        "ORDER BY time ASC"
    )
    PING: str = "SELECT 1"


_SQL: _GatewaySQL = _GatewaySQL()


class GatewayAdapter:
    """Async adapter for the ``db_gateway`` PostgreSQL database.

    Owns one ``asyncpg.Pool`` (``min_size=2, max_size=10``). Writes are
    idempotent (``ON CONFLICT ... DO UPDATE``); reads return frozen
    Pydantic models. Errors propagate verbatim — callers handle
    best-effort policy.

    Attributes:
        dsn: PostgreSQL DSN (read-only).
    """

    def __init__(self, dsn: str) -> None:
        """Initialise without connecting.

        Args:
            dsn: PostgreSQL connection string for ``db_gateway``.
        """
        self._dsn: str = dsn
        self._pool: asyncpg.Pool | None = None

    @property
    def dsn(self) -> str:
        """Return the configured DSN (read-only)."""
        return self._dsn

    async def connect(self) -> None:
        """Open the connection pool. Idempotent — second call is a no-op.

        Raises:
            asyncpg.PostgresError: When the server is unreachable.
            OSError: When the network layer fails.
        """
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
            init=_init_connection,
        )
        logger.info("GatewayAdapter pool opened (min=2, max=10)")

    async def close(self) -> None:
        """Close the pool. Idempotent — second call is a no-op."""
        if self._pool is None:
            return
        pool = self._pool
        self._pool = None
        await pool.close()
        logger.info("GatewayAdapter pool closed")

    async def __aenter__(self) -> GatewayAdapter:
        """Open the pool and return self."""
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Close the pool."""
        await self.close()

    async def ping(self) -> bool:
        """Run ``SELECT 1`` through the pool to confirm liveness.

        Returns:
            ``True`` when the query returns ``1``; ``False`` otherwise.

        Raises:
            RuntimeError: When the pool has not been opened.
            asyncpg.PostgresError: When the server is unreachable.
        """
        pool = self._require_pool()
        result: object = await pool.fetchval(_SQL.PING)
        return result == 1

    def _require_pool(self) -> asyncpg.Pool:
        """Return the live pool or raise if ``connect()`` was never called."""
        if self._pool is None:
            raise RuntimeError(
                "GatewayAdapter is not connected. Call 'await adapter.connect()' "
                "or use 'async with adapter:' first."
            )
        return self._pool

    async def read_daily_performance(
        self,
        strategy_id: str,
        days: int = 90,
    ) -> list[DailyPerformanceRow]:
        """Return the daily-performance rows in the last ``days`` days, ascending by time.

        ``days`` is a window of **calendar days**, not a row count (it previously
        mapped straight to ``LIMIT``). The count returned is the number of rows
        recorded inside that window.

        Args:
            strategy_id: Strategy identifier.
            days: Size of the look-back window in calendar days, inclusive of
                today (UTC). Defaults to 90.

        Returns:
            ``DailyPerformanceRow`` list ordered by ``time`` ascending.

        Raises:
            RuntimeError: When the pool has not been opened.
            asyncpg.PostgresError: On database error.
        """
        pool = self._require_pool()
        records: list[asyncpg.Record] = await pool.fetch(
            _SQL.SELECT_DAILY_PERFORMANCE_RECENT, strategy_id, days
        )
        return [_record_to_daily_performance(r) for r in records]

    async def read_portfolio_snapshots(
        self,
        days: int = 90,
    ) -> list[PortfolioSnapshotRow]:
        """Return the portfolio snapshots in the last ``days`` days, ascending by time.

        ``days`` is a window of **calendar days**, not a row count (it previously mapped
        straight to ``LIMIT``).

        Args:
            days: Size of the look-back window in calendar days, inclusive of
                today (UTC). Defaults to 90.

        Returns:
            ``PortfolioSnapshotRow`` list ordered by ``time`` ascending.

        Raises:
            RuntimeError: When the pool has not been opened.
            asyncpg.PostgresError: On database error.
        """
        pool = self._require_pool()
        records: list[asyncpg.Record] = await pool.fetch(
            _SQL.SELECT_PORTFOLIO_SNAPSHOTS_RECENT, days
        )
        return [_record_to_portfolio_snapshot(r) for r in records]


def _record_to_daily_performance(record: asyncpg.Record) -> DailyPerformanceRow:
    """Coerce an ``asyncpg.Record`` for ``daily_performance`` into a Pydantic model.

    The ``metadata`` JSONB column arrives as ``dict`` because
    ``_init_connection`` registered a JSON codec.
    """
    row: dict[str, object] = dict(record)
    metadata: object = row.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    time_val: object = row["time"]
    if not isinstance(time_val, datetime):
        raise TypeError(f"daily_performance.time must be datetime, got {type(time_val).__name__}")
    strategy_id: object = row["strategy_id"]
    return DailyPerformanceRow(
        time=time_val,
        strategy_id=str(strategy_id),
        daily_return=_float_or_none(row.get("daily_return")),
        cumulative_return=_float_or_none(row.get("cumulative_return")),
        total_value=_float_or_none(row.get("total_value")),
        cash_balance=_float_or_none(row.get("cash_balance")),
        max_drawdown=_float_or_none(row.get("max_drawdown")),
        sharpe_ratio=_float_or_none(row.get("sharpe_ratio")),
        metadata=metadata,
    )


def _record_to_portfolio_snapshot(record: asyncpg.Record) -> PortfolioSnapshotRow:
    """Coerce an ``asyncpg.Record`` for ``portfolio_snapshot`` into a Pydantic model.

    The ``allocation`` JSONB column arrives as ``dict`` because
    ``_init_connection`` registered a JSON codec.
    """
    row: dict[str, object] = dict(record)
    allocation: object = row.get("allocation")
    if not isinstance(allocation, dict):
        allocation = {}
    time_val: object = row["time"]
    if not isinstance(time_val, datetime):
        raise TypeError(f"portfolio_snapshot.time must be datetime, got {type(time_val).__name__}")
    active_raw: object = row.get("active_strategies", 0)
    if isinstance(active_raw, (int, float)):
        active_strategies = int(active_raw)
    elif isinstance(active_raw, str):
        try:
            active_strategies = int(active_raw)
        except ValueError:
            active_strategies = 0
    else:
        active_strategies = 0
    return PortfolioSnapshotRow(
        time=time_val,
        total_portfolio=_float_or_none(row.get("total_portfolio")),
        weighted_return=_float_or_none(row.get("weighted_return")),
        combined_drawdown=_float_or_none(row.get("combined_drawdown")),
        active_strategies=active_strategies,
        allocation=allocation,
    )


def _float_or_none(value: object) -> float | None:
    """Coerce a value to ``float``, returning ``None`` for nulls / failures."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


__all__: list[str] = ["GatewayAdapter"]
