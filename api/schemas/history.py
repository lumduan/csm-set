"""Response schemas for ``/api/v1/history/*`` endpoints.

The Phase 2–4 adapter result models in :mod:`csm.adapters.models` are already
frozen Pydantic v2 models with full annotations and serialise cleanly to
JSON, so they are reused as ``response_model`` directly. This module exists
only to give the history router a local import surface (``api.schemas.history``)
and to host any view-level constants that should not leak into
``csm.adapters``.
"""

from __future__ import annotations

from csm.adapters.models import (
    BacktestSummaryRow,
    DailyPerformanceRow,
    EquityPoint,
    PortfolioSnapshotRow,
    SignalSnapshotDoc,
    TradeRow,
)

DEFAULT_STRATEGY_ID: str = "csm-set"
"""Strategy id used by every history endpoint when the caller omits ``strategy_id``."""


__all__: list[str] = [
    "DEFAULT_STRATEGY_ID",
    "BacktestSummaryRow",
    "DailyPerformanceRow",
    "EquityPoint",
    "PortfolioSnapshotRow",
    "SignalSnapshotDoc",
    "TradeRow",
]
