"""Response schemas for ``/api/v1/history/*`` endpoints.

The Phase 2–4 adapter result models in :mod:`csm.adapters.models` are already
frozen Pydantic v2 models with full annotations and serialise cleanly to
JSON, so they are reused as ``response_model`` directly. This module exists
only to give the history router a local import surface (``api.schemas.history``)
and to host any view-level constants that should not leak into
``csm.adapters``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class StrategyReportResponse(BaseModel):
    """Wrapper around the latest persisted ``extended_data.report`` block.

    The ``report`` payload is returned as a loosely-typed ``dict`` here so that
    the strategy service does not couple to the Phase 3 gateway schema before
    that schema is published. Downstream consumers parse it through their own
    typed model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str = Field(description="Strategy identifier whose report is returned.")
    as_of: datetime = Field(description="Snapshot time of the underlying daily_performance row.")
    report: dict[str, Any] = Field(description="The strategy report payload, verbatim.")


__all__: list[str] = [
    "DEFAULT_STRATEGY_ID",
    "BacktestSummaryRow",
    "DailyPerformanceRow",
    "EquityPoint",
    "PortfolioSnapshotRow",
    "SignalSnapshotDoc",
    "StrategyReportResponse",
    "TradeRow",
]
