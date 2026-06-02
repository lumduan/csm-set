"""Build the standard ingestion-contract payload posted to the API Gateway.

The gateway accepts daily reports from any strategy via the documented
``POST /api/v1/ingest/daily-report`` contract:

    {
        "strategy_metadata":   {"id", "type", "last_updated"},
        "performance_metrics": {"daily_pnl", "equity_curve", "max_drawdown",
                                "sharpe_ratio"},
        "current_exposure":    {"total_value", "cash_balance",
                                "positions_count"},
        "extended_data":       {"report": <StrategyReport JSON>, ...}
    }

This module is a pure dict builder. Network I/O lives in
:mod:`csm.adapters.gateway_client`; lifecycle wiring lives in
:mod:`csm.adapters.__init__`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from csm.live.portfolio import LivePortfolioMetrics
    from csm.research.strategy_report_models import StrategyReport


DEFAULT_STRATEGY_TYPE: str = "EQUITY_MOMENTUM"


def _series_to_equity_curve(series: pd.Series) -> list[dict[str, str]]:
    """Convert a tz-aware pandas Series indexed by date into the contract shape.

    Returns at most one point per UTC date (the last value on each date).
    Values are emitted as strings so the gateway's ``Decimal`` validation
    receives lossless input.
    """
    if series.empty:
        return []
    idx = series.index
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize("UTC")
    elif str(idx.tz) != "UTC":
        idx = idx.tz_convert("UTC")
    by_date: dict[str, str] = {}
    for ts, value in zip(idx, series.to_numpy(), strict=True):
        date_str: str = ts.strftime("%Y-%m-%d")
        by_date[date_str] = f"{float(value):.4f}"
    return [{"date": d, "value": v} for d, v in sorted(by_date.items())]


def build_ingestion_payload(
    *,
    strategy_id: str,
    strategy_type: str,
    last_updated: datetime,
    live_metrics: LivePortfolioMetrics,
    equity_curve: pd.Series,
    report: StrategyReport | None = None,
) -> dict[str, Any]:
    """Assemble the gateway ingestion payload from already-computed inputs.

    The caller is responsible for ensuring that ``equity_curve`` reflects
    the same portfolio the scalar metrics describe. When ``equity_curve``
    is empty, a single-point fallback is emitted at ``last_updated``'s date
    with ``live_metrics.total_value`` so the gateway's ``min_length=1``
    validator is satisfied.

    Args:
        strategy_id: Stable identifier (e.g. ``"csm-set"``).
        strategy_type: Discriminator that drives the dashboard's
            ``StrategyAdapterFactory`` (e.g. ``"EQUITY_MOMENTUM"``).
        last_updated: UTC timestamp of this report (the "as-of" of the run).
        live_metrics: Scalar metrics for the day.
        equity_curve: Time-indexed equity values used to populate the
            ``performance_metrics.equity_curve`` field.
        report: Optional fully-built :class:`StrategyReport`; when present
            it lands under ``extended_data.report`` and the gateway
            persists it into ``strategy_report_snapshot``.

    Returns:
        A plain dict matching the gateway's ``StrategyPayload`` schema.
        Values are JSON-safe (``str`` for monetary/ratio fields).
    """
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=UTC)

    curve = _series_to_equity_curve(equity_curve)
    if not curve:
        curve = [
            {
                "date": last_updated.strftime("%Y-%m-%d"),
                "value": f"{float(live_metrics.total_value):.4f}",
            }
        ]

    payload: dict[str, Any] = {
        "strategy_metadata": {
            "id": strategy_id,
            "type": strategy_type,
            "last_updated": last_updated.isoformat(),
        },
        "performance_metrics": {
            "daily_pnl": f"{float(live_metrics.daily_pnl):.4f}",
            "equity_curve": curve,
            "max_drawdown": f"{float(live_metrics.max_drawdown):.4f}",
            "sharpe_ratio": f"{float(live_metrics.sharpe_ratio):.4f}",
        },
        "current_exposure": {
            "total_value": f"{float(live_metrics.total_value):.4f}",
            "cash_balance": f"{float(live_metrics.cash_balance):.4f}",
            "positions_count": int(live_metrics.positions_count),
        },
        "extended_data": {},
    }
    if report is not None:
        payload["extended_data"]["report"] = report.model_dump(mode="json")
    return payload


__all__: list[str] = ["DEFAULT_STRATEGY_TYPE", "build_ingestion_payload"]
