"""Adapter-level Pydantic models for db_csm_set / csm_logs read return types.

These frozen models form the typed boundary between ``PostgresAdapter`` /
``MongoAdapter`` reads and the rest of the application. Phase 6 history
routers wrap or re-export these types when shaping API responses.
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


class BacktestResultDoc(BaseModel):
    """One document of the ``csm_logs.backtest_results`` collection.

    Stores the full backtest payload — config snapshot, summary metrics, equity
    curve, and trade list — keyed on ``run_id``. Re-running a backtest with the
    same ``run_id`` replaces the prior document.

    Attributes:
        run_id: Unique identifier for the backtest run (natural primary key).
        strategy_id: Strategy identifier (e.g. ``"csm-set"``).
        created_at: tz-aware timestamp (UTC) when the result was generated.
        config: Backtest configuration as a JSON-serialisable dict.
        metrics: Summary metrics keyed by metric name (sharpe, max_dd, …).
        equity_curve: ``date -> nav`` mapping for the full backtest window.
        trades: Per-trade records (typically ``DataFrame.to_dict('records')``).
    """

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description="Unique backtest run identifier.")
    strategy_id: str = Field(description="Strategy identifier.")
    created_at: datetime = Field(description="tz-aware result-generation timestamp (UTC).")
    config: dict[str, object] = Field(description="Backtest configuration snapshot.")
    metrics: dict[str, float] = Field(description="Summary metrics keyed by metric name.")
    equity_curve: dict[str, float] = Field(description="date -> nav equity curve mapping.")
    trades: list[dict[str, object]] = Field(description="Per-trade records.")


class SignalSnapshotDoc(BaseModel):
    """One document of the ``csm_logs.signal_snapshots`` collection.

    Stores a daily ranking array for a strategy, keyed on
    ``(strategy_id, date)``. Re-running daily refresh upserts the document.

    Attributes:
        strategy_id: Strategy identifier (e.g. ``"csm-set"``).
        date: tz-aware timestamp (UTC) representing the trading day.
        rankings: Per-symbol ranking records (one entry per ranked symbol).
    """

    model_config = ConfigDict(frozen=True)

    strategy_id: str = Field(description="Strategy identifier.")
    date: datetime = Field(description="tz-aware trading-day timestamp (UTC).")
    rankings: list[dict[str, object]] = Field(description="Per-symbol ranking records.")


class ModelParamsDoc(BaseModel):
    """One document of the ``csm_logs.model_params`` collection.

    Stores a versioned snapshot of the strategy's tunable parameters, keyed on
    ``(strategy_id, version)`` so historical configurations can be replayed.

    Attributes:
        strategy_id: Strategy identifier (e.g. ``"csm-set"``).
        version: Free-form version label (e.g. ``"2026-05-07"`` or ``"v0.7.1"``).
        params: Parameter dict (formation period, top-quintile threshold, …).
        created_at: tz-aware timestamp (UTC) when the version was first written.
    """

    model_config = ConfigDict(frozen=True)

    strategy_id: str = Field(description="Strategy identifier.")
    version: str = Field(description="Parameter snapshot version label.")
    params: dict[str, object] = Field(description="Parameter snapshot.")
    created_at: datetime = Field(description="tz-aware first-write timestamp (UTC).")


class BacktestSummaryRow(BaseModel):
    """Slim projection of ``csm_logs.backtest_results`` for listing endpoints.

    Returned by :meth:`csm.adapters.mongo.MongoAdapter.list_backtest_results`.
    Excludes the potentially-large ``equity_curve`` and ``trades`` arrays so
    listing payloads stay cheap.

    Attributes:
        run_id: Unique backtest run identifier.
        strategy_id: Strategy identifier.
        created_at: tz-aware result-generation timestamp (UTC).
        metrics: Summary metrics keyed by metric name.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description="Unique backtest run identifier.")
    strategy_id: str = Field(description="Strategy identifier.")
    created_at: datetime = Field(description="tz-aware result-generation timestamp (UTC).")
    metrics: dict[str, float] = Field(description="Summary metrics keyed by metric name.")


__all__: list[str] = [
    "BacktestLogRow",
    "BacktestResultDoc",
    "BacktestSummaryRow",
    "EquityPoint",
    "ModelParamsDoc",
    "SignalSnapshotDoc",
    "TradeRow",
]
