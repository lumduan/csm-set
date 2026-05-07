"""Private-mode history endpoints — ``/api/v1/history/*``.

These read-only routes wrap the Phase 2–4 adapter ``read_*`` methods so
external dashboards and an API Gateway can query csm-set time series without
touching the local Parquet store. The router is mounted only when
``settings.public_mode`` is ``False`` and is gated by ``APIKeyMiddleware``
via the new ``PROTECTED_PREFIXES`` set in :mod:`api.security`.

Each endpoint returns ``HTTP 503`` when its corresponding adapter slot on
:class:`csm.adapters.AdapterManager` is ``None`` (i.e. ``db_write_enabled``
is ``False`` or the relevant DSN is unset). ``GET /signals`` additionally
returns ``HTTP 404`` when no snapshot document matches the
``(strategy_id, date)`` filter. List endpoints return ``200 []`` for
empty result sets — empty lists are a valid query outcome and 503 is
reserved for the disabled-adapter case.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_adapter_manager
from api.schemas.errors import ProblemDetail
from api.schemas.history import (
    DEFAULT_STRATEGY_ID,
    BacktestSummaryRow,
    DailyPerformanceRow,
    EquityPoint,
    PortfolioSnapshotRow,
    SignalSnapshotDoc,
    TradeRow,
)
from csm.adapters import AdapterManager

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/history", tags=["history"])

T = TypeVar("T")


def _require(adapter: T | None, name: str) -> T:
    """Return ``adapter`` or raise ``HTTPException(503)`` when it is ``None``.

    Args:
        adapter: The adapter slot from :class:`AdapterManager` to validate.
        name: Human-readable adapter name for the error detail
            (e.g. ``"postgres"``, ``"mongo"``, ``"gateway"``).

    Returns:
        The non-``None`` adapter.

    Raises:
        HTTPException: ``503`` when ``adapter`` is ``None``.
    """

    if adapter is None:
        raise HTTPException(
            status_code=503,
            detail=(f"{name} adapter unavailable (db_write_enabled is false or DSN missing)."),
        )
    return adapter


_ADAPTER_DOWN_RESPONSES: dict[int | str, dict[str, object]] = {
    503: {
        "description": "Adapter unavailable (db_write_enabled is false or DSN missing).",
        "model": ProblemDetail,
    },
}

_AUTH_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {
        "description": "Missing or invalid X-API-Key header.",
        "model": ProblemDetail,
    },
}


@router.get(
    "/equity-curve",
    response_model=list[EquityPoint],
    summary="Historical equity curve",
    description=(
        "Return up to ``days`` most-recent rows of the strategy equity curve "
        "from ``db_csm_set.equity_curve``, ascending by time."
    ),
    responses={**_ADAPTER_DOWN_RESPONSES, **_AUTH_RESPONSES},
)
async def get_equity_curve(
    strategy_id: str = Query(
        default=DEFAULT_STRATEGY_ID,
        description="Strategy identifier.",
        examples=["csm-set"],
    ),
    days: int = Query(
        default=90,
        ge=1,
        le=3650,
        description="Number of most-recent days to return (ascending by time).",
    ),
    manager: AdapterManager = Depends(get_adapter_manager),
) -> list[EquityPoint]:
    """Read the strategy equity curve from ``db_csm_set.equity_curve``."""

    pg = _require(manager.postgres, "postgres")
    return await pg.read_equity_curve(strategy_id, days)


@router.get(
    "/trades",
    response_model=list[TradeRow],
    summary="Historical trade log",
    description=(
        "Return up to ``limit`` most-recent trades from "
        "``db_csm_set.trade_history``, descending by time."
    ),
    responses={**_ADAPTER_DOWN_RESPONSES, **_AUTH_RESPONSES},
)
async def get_trades(
    strategy_id: str = Query(
        default=DEFAULT_STRATEGY_ID,
        description="Strategy identifier.",
        examples=["csm-set"],
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of trades to return (descending by time).",
    ),
    manager: AdapterManager = Depends(get_adapter_manager),
) -> list[TradeRow]:
    """Read the strategy trade log from ``db_csm_set.trade_history``."""

    pg = _require(manager.postgres, "postgres")
    return await pg.read_trade_history(strategy_id, limit)


@router.get(
    "/performance",
    response_model=list[DailyPerformanceRow],
    summary="Daily performance metrics",
    description=(
        "Return up to ``days`` most-recent rows from "
        "``db_gateway.daily_performance`` for the given strategy, ascending by time."
    ),
    responses={**_ADAPTER_DOWN_RESPONSES, **_AUTH_RESPONSES},
)
async def get_performance(
    strategy_id: str = Query(
        default=DEFAULT_STRATEGY_ID,
        description="Strategy identifier.",
        examples=["csm-set"],
    ),
    days: int = Query(
        default=30,
        ge=1,
        le=3650,
        description="Number of most-recent days to return (ascending by time).",
    ),
    manager: AdapterManager = Depends(get_adapter_manager),
) -> list[DailyPerformanceRow]:
    """Read daily performance metrics from ``db_gateway.daily_performance``."""

    gw = _require(manager.gateway, "gateway")
    return await gw.read_daily_performance(strategy_id, days)


@router.get(
    "/portfolio-snapshots",
    response_model=list[PortfolioSnapshotRow],
    summary="Portfolio snapshots",
    description=(
        "Return up to ``days`` most-recent cross-strategy portfolio snapshots "
        "from ``db_gateway.portfolio_snapshot``, ascending by time."
    ),
    responses={**_ADAPTER_DOWN_RESPONSES, **_AUTH_RESPONSES},
)
async def get_portfolio_snapshots(
    days: int = Query(
        default=30,
        ge=1,
        le=3650,
        description="Number of most-recent days to return (ascending by time).",
    ),
    manager: AdapterManager = Depends(get_adapter_manager),
) -> list[PortfolioSnapshotRow]:
    """Read portfolio snapshots from ``db_gateway.portfolio_snapshot``."""

    gw = _require(manager.gateway, "gateway")
    return await gw.read_portfolio_snapshots(days)


@router.get(
    "/backtests",
    response_model=list[BacktestSummaryRow],
    summary="Backtest summaries",
    description=(
        "Return up to ``limit`` most-recent backtest summary rows from "
        "``csm_logs.backtest_results``, descending by ``created_at``. The "
        "potentially-large ``equity_curve`` and ``trades`` arrays are excluded "
        "from this listing — fetch by ``run_id`` for the full document."
    ),
    responses={**_ADAPTER_DOWN_RESPONSES, **_AUTH_RESPONSES},
)
async def list_backtests(
    strategy_id: str = Query(
        default=DEFAULT_STRATEGY_ID,
        description="Strategy identifier.",
        examples=["csm-set"],
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=1000,
        description="Maximum number of summary rows to return.",
    ),
    manager: AdapterManager = Depends(get_adapter_manager),
) -> list[BacktestSummaryRow]:
    """List recent backtest summaries from ``csm_logs.backtest_results``."""

    mongo = _require(manager.mongo, "mongo")
    return await mongo.list_backtest_results(strategy_id, limit)


@router.get(
    "/signals",
    response_model=SignalSnapshotDoc,
    summary="Signal snapshot for a given trading day",
    description=(
        "Return the signal snapshot document for ``(strategy_id, date)`` from "
        "``csm_logs.signal_snapshots``. The ``date`` query parameter is the "
        "trading day in ``YYYY-MM-DD`` form; the lookup is keyed on UTC midnight."
    ),
    responses={
        **_ADAPTER_DOWN_RESPONSES,
        **_AUTH_RESPONSES,
        404: {
            "description": "No signal snapshot for the given (strategy_id, date).",
            "model": ProblemDetail,
        },
    },
)
async def get_signal_snapshot(
    date_: date = Query(
        alias="date",
        description=(
            "Trading day to fetch (``YYYY-MM-DD``). Resolved to UTC midnight "
            "before lookup, matching how snapshots are stored."
        ),
    ),
    strategy_id: str = Query(
        default=DEFAULT_STRATEGY_ID,
        description="Strategy identifier.",
        examples=["csm-set"],
    ),
    manager: AdapterManager = Depends(get_adapter_manager),
) -> SignalSnapshotDoc:
    """Read the signal snapshot for ``(strategy_id, date)``."""

    mongo = _require(manager.mongo, "mongo")
    snapshot_at: datetime = datetime(date_.year, date_.month, date_.day, tzinfo=UTC)
    doc = await mongo.read_signal_snapshot(strategy_id, snapshot_at)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"No signal snapshot for strategy_id={strategy_id!r} date={date_.isoformat()}.",
        )
    return doc


__all__: list[str] = ["router"]
