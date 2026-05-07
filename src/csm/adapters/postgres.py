"""PostgresAdapter for db_csm_set write-back and history reads.

Owns an ``asyncpg`` connection pool and exposes idempotent write methods for
the three ``db_csm_set`` tables (``equity_curve``, ``trade_history``,
``backtest_log``) plus typed read methods returning frozen Pydantic models.

The schemas themselves are owned by the ``quant-infra-db`` stack and are not
declared here — ``PostgresAdapter`` only writes against existing tables.

Lifecycle:

>>> async with PostgresAdapter(dsn) as pg:  # doctest: +SKIP
...     await pg.write_equity_curve("csm-set", equity_series)

For best-effort persistence, callers wrap each call in their own
``try/except`` and log a warning on failure (see PLAN.md Phase 5 hooks).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import asyncpg

from csm.adapters.models import BacktestLogRow, EquityPoint, TradeRow

if TYPE_CHECKING:
    import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SQLStatements:
    """Centralised SQL statements for ``db_csm_set``.

    No inline string concatenation in adapter methods — every statement lives
    here and is referenced by attribute. Idempotency clauses are baked into
    each ``INSERT``.
    """

    UPSERT_EQUITY_CURVE: str = (
        "INSERT INTO equity_curve (time, strategy_id, equity) "
        "VALUES ($1, $2, $3) "
        "ON CONFLICT (time, strategy_id) DO UPDATE SET equity = EXCLUDED.equity"
    )
    UPSERT_TRADE_HISTORY: str = (
        "INSERT INTO trade_history "
        "(time, strategy_id, symbol, side, quantity, price, commission) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) "
        "ON CONFLICT (strategy_id, time, symbol, side) DO UPDATE SET "
        "quantity = EXCLUDED.quantity, "
        "price = EXCLUDED.price, "
        "commission = EXCLUDED.commission"
    )
    INSERT_BACKTEST_LOG: str = (
        "INSERT INTO backtest_log (run_id, strategy_id, started_at, config, summary) "
        "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb) "
        "ON CONFLICT (run_id) DO NOTHING"
    )
    SELECT_EQUITY_CURVE_RECENT: str = (
        "SELECT time, strategy_id, equity FROM ("
        "  SELECT time, strategy_id, equity FROM equity_curve"
        "  WHERE strategy_id = $1"
        "  ORDER BY time DESC LIMIT $2"
        ") sub "
        "ORDER BY time ASC"
    )
    SELECT_TRADE_HISTORY_RECENT: str = (
        "SELECT time, strategy_id, symbol, side, quantity, price, commission "
        "FROM trade_history "
        "WHERE strategy_id = $1 "
        "ORDER BY time DESC "
        "LIMIT $2"
    )
    SELECT_BACKTEST_LOG_RECENT: str = (
        "SELECT run_id, strategy_id, started_at AS created_at, config, summary "
        "FROM backtest_log "
        "WHERE ($1::text IS NULL OR strategy_id = $1) "
        "ORDER BY started_at DESC "
        "LIMIT $2"
    )
    PING: str = "SELECT 1"


_SQL: _SQLStatements = _SQLStatements()


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register a JSONB codec on every pooled connection.

    asyncpg returns JSONB columns as raw strings unless a codec is set. We
    register ``json.dumps`` / ``json.loads`` so adapter callers can pass and
    receive plain Python dicts.
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )


class PostgresAdapter:
    """Async adapter for the ``db_csm_set`` PostgreSQL database.

    Owns one ``asyncpg.Pool`` (``min_size=2, max_size=10``). Writes are
    idempotent (``ON CONFLICT ... DO UPDATE/DO NOTHING``); reads return
    frozen Pydantic models. Errors propagate verbatim — callers handle
    best-effort policy.

    Attributes:
        dsn: PostgreSQL DSN (read-only).
    """

    def __init__(self, dsn: str) -> None:
        """Initialise without connecting.

        Args:
            dsn: PostgreSQL connection string for ``db_csm_set``.
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
        logger.info("PostgresAdapter pool opened (min=2, max=10)")

    async def close(self) -> None:
        """Close the pool. Idempotent — second call is a no-op."""
        if self._pool is None:
            return
        pool = self._pool
        self._pool = None
        await pool.close()
        logger.info("PostgresAdapter pool closed")

    async def __aenter__(self) -> PostgresAdapter:
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
                "PostgresAdapter is not connected. Call 'await adapter.connect()' "
                "or use 'async with adapter:' first."
            )
        return self._pool

    async def write_equity_curve(self, strategy_id: str, series: pd.Series) -> int:
        """Upsert ``(time, strategy_id, equity)`` rows.

        Args:
            strategy_id: Strategy identifier (e.g. ``"csm-set"``).
            series: Pandas Series indexed by tz-aware timestamp; values are
                strategy equity (``float``-coercible).

        Returns:
            Number of rows submitted to the database.

        Raises:
            RuntimeError: When the pool has not been opened.
            asyncpg.PostgresError: On database error.
        """
        pool = self._require_pool()
        rows: list[tuple[Any, str, float]] = [
            (ts, strategy_id, float(equity)) for ts, equity in series.items()
        ]
        if not rows:
            return 0
        await pool.executemany(_SQL.UPSERT_EQUITY_CURVE, rows)
        logger.debug("write_equity_curve strategy=%s rows=%d", strategy_id, len(rows))
        return len(rows)

    async def write_trade_history(self, strategy_id: str, trades: pd.DataFrame) -> int:
        """Upsert trade rows.

        Args:
            strategy_id: Strategy identifier.
            trades: DataFrame with columns ``time``, ``symbol``, ``side``,
                ``quantity``, ``price``, ``commission``.

        Returns:
            Number of rows submitted to the database.

        Raises:
            RuntimeError: When the pool has not been opened.
            KeyError: When required columns are missing.
            asyncpg.PostgresError: On database error.
        """
        pool = self._require_pool()
        if trades.empty:
            return 0
        required: list[str] = [
            "time",
            "symbol",
            "side",
            "quantity",
            "price",
            "commission",
        ]
        missing: list[str] = [c for c in required if c not in trades.columns]
        if missing:
            raise KeyError(f"trades DataFrame is missing required columns: {missing}")
        rows: list[tuple[Any, str, str, str, float, float, float]] = [
            (
                row.time,
                strategy_id,
                str(row.symbol),
                str(row.side),
                float(row.quantity),
                float(row.price),
                float(row.commission),
            )
            for row in trades.itertuples(index=False)
        ]
        await pool.executemany(_SQL.UPSERT_TRADE_HISTORY, rows)
        logger.debug("write_trade_history strategy=%s rows=%d", strategy_id, len(rows))
        return len(rows)

    async def write_backtest_log(
        self,
        run_id: str,
        strategy_id: str,
        config: dict[str, object],
        summary: dict[str, object],
    ) -> None:
        """Insert a single backtest log row. ``ON CONFLICT (run_id) DO NOTHING``.

        Args:
            run_id: Unique backtest run identifier (natural primary key).
            strategy_id: Strategy identifier.
            config: Backtest configuration as a JSON-serialisable dict.
            summary: Summary metrics as a JSON-serialisable dict (typically
                ``BacktestResult.metrics_dict()``).

        Raises:
            RuntimeError: When the pool has not been opened.
            TypeError: When ``config`` or ``summary`` is not JSON-serialisable.
            asyncpg.PostgresError: On database error.
        """
        pool = self._require_pool()
        await pool.execute(
            _SQL.INSERT_BACKTEST_LOG,
            run_id,
            strategy_id,
            datetime.now(UTC),
            config,
            summary,
        )
        logger.debug("write_backtest_log run_id=%s strategy=%s", run_id, strategy_id)

    async def read_equity_curve(self, strategy_id: str, days: int = 90) -> list[EquityPoint]:
        """Return up to the last ``days`` equity points, ascending by time.

        Args:
            strategy_id: Strategy identifier.
            days: Maximum number of rows to return (most recent first, then
                re-ordered ascending). Defaults to 90.

        Returns:
            ``EquityPoint`` list ordered by ``time`` ascending.

        Raises:
            RuntimeError: When the pool has not been opened.
            asyncpg.PostgresError: On database error.
        """
        pool = self._require_pool()
        records: list[asyncpg.Record] = await pool.fetch(
            _SQL.SELECT_EQUITY_CURVE_RECENT, strategy_id, days
        )
        return [EquityPoint.model_validate(dict(r)) for r in records]

    async def read_trade_history(self, strategy_id: str, limit: int = 100) -> list[TradeRow]:
        """Return up to the most recent ``limit`` trades, descending by time.

        Args:
            strategy_id: Strategy identifier.
            limit: Maximum number of rows to return. Defaults to 100.

        Returns:
            ``TradeRow`` list ordered by ``time`` descending.

        Raises:
            RuntimeError: When the pool has not been opened.
            asyncpg.PostgresError: On database error.
        """
        pool = self._require_pool()
        records: list[asyncpg.Record] = await pool.fetch(
            _SQL.SELECT_TRADE_HISTORY_RECENT, strategy_id, limit
        )
        return [TradeRow.model_validate(dict(r)) for r in records]

    async def read_backtest_log(
        self,
        strategy_id: str | None = None,
        limit: int = 50,
    ) -> list[BacktestLogRow]:
        """Return the most recent ``limit`` backtest log rows.

        Args:
            strategy_id: When set, filter to rows for this strategy. ``None``
                returns rows across all strategies.
            limit: Maximum number of rows to return. Defaults to 50.

        Returns:
            ``BacktestLogRow`` list ordered by ``created_at`` descending.

        Raises:
            RuntimeError: When the pool has not been opened.
            asyncpg.PostgresError: On database error.
        """
        pool = self._require_pool()
        records: list[asyncpg.Record] = await pool.fetch(
            _SQL.SELECT_BACKTEST_LOG_RECENT, strategy_id, limit
        )
        return [_record_to_backtest_log(r) for r in records]


def _record_to_backtest_log(record: asyncpg.Record) -> BacktestLogRow:
    """Coerce an ``asyncpg.Record`` for ``backtest_log`` into a Pydantic model.

    The JSONB columns arrive as ``dict`` because ``_init_connection`` registered
    a JSON codec; ``created_at`` arrives as ``datetime``.
    """
    row: dict[str, object] = dict(record)
    config: object = row.get("config")
    summary: object = row.get("summary")
    if not isinstance(config, dict):
        config = {}
    if not isinstance(summary, dict):
        summary = {}
    created: object = row["created_at"]
    if not isinstance(created, datetime):
        raise TypeError(f"backtest_log.created_at must be datetime, got {type(created).__name__}")
    run_id: object = row["run_id"]
    strategy_id: object = row["strategy_id"]
    return BacktestLogRow(
        run_id=str(run_id),
        strategy_id=str(strategy_id),
        created_at=created,
        config=config,
        summary=summary,
    )


__all__: list[str] = ["PostgresAdapter"]
