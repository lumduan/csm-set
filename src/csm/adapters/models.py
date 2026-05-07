"""Adapter-level Pydantic models for db_csm_set read return types.

These frozen models form the typed boundary between ``PostgresAdapter`` reads
and the rest of the application. Phase 6 history routers wrap or re-export
these types when shaping API responses.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EquityPoint(BaseModel):
    """One row of the ``db_csm_set.equity_curve`` hypertable.

    Attributes:
        time: tz-aware timestamp (UTC).
        strategy_id: Strategy identifier (e.g. ``"csm-set"``).
        equity: Strategy equity value at ``time``.
    """

    model_config = ConfigDict(frozen=True)

    time: datetime = Field(description="tz-aware timestamp (UTC).")
    strategy_id: str = Field(description="Strategy identifier.")
    equity: float = Field(description="Strategy equity value.")


class TradeRow(BaseModel):
    """One row of the ``db_csm_set.trade_history`` hypertable.

    Attributes:
        time: tz-aware timestamp (UTC) when the trade was recorded.
        strategy_id: Strategy identifier (e.g. ``"csm-set"``).
        symbol: Traded ticker (e.g. ``"PTT"``).
        side: ``"buy"`` or ``"sell"``.
        quantity: Number of shares (positive).
        price: Execution price.
        commission: Commission paid (THB, includes broker + venue fees + VAT).
    """

    model_config = ConfigDict(frozen=True)

    time: datetime = Field(description="tz-aware trade timestamp (UTC).")
    strategy_id: str = Field(description="Strategy identifier.")
    symbol: str = Field(description="Traded ticker.")
    side: str = Field(description="'buy' or 'sell'.")
    quantity: float = Field(description="Number of shares.")
    price: float = Field(description="Execution price.")
    commission: float = Field(description="Total commission (THB).")


class BacktestLogRow(BaseModel):
    """One row of the ``db_csm_set.backtest_log`` table.

    ``config`` and ``summary`` are stored as JSONB on the database side and
    surfaced as Python dicts.

    Attributes:
        run_id: Unique identifier for the backtest run.
        strategy_id: Strategy identifier (e.g. ``"csm-set"``).
        created_at: tz-aware timestamp (UTC) when the row was inserted.
        config: Backtest configuration as a JSON-serialisable dict.
        summary: Summary metrics (typically the output of
            :meth:`csm.research.backtest.BacktestResult.metrics_dict`).
    """

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description="Unique backtest run identifier.")
    strategy_id: str = Field(description="Strategy identifier.")
    created_at: datetime = Field(description="tz-aware row creation timestamp (UTC).")
    config: dict[str, object] = Field(description="Backtest config (JSONB).")
    summary: dict[str, object] = Field(description="Backtest summary metrics (JSONB).")


__all__: list[str] = ["BacktestLogRow", "EquityPoint", "TradeRow"]
