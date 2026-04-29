"""Pydantic state models for the Phase 4 portfolio overlay pipeline."""

from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from csm.risk.regime import RegimeState


class CircuitBreakerState(StrEnum):
    """Drawdown circuit breaker state machine.

    Phase 4.5 adds TRIPPED and RECOVERING states.
    """

    NORMAL = "NORMAL"


class OverlayJournalEntry(BaseModel):
    """Record of a single overlay decision during rebalance."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    overlay: str
    asof: pd.Timestamp
    decision: str
    inputs: dict[str, float] = Field(default_factory=dict)
    outputs: dict[str, float] = Field(default_factory=dict)


class PortfolioState(BaseModel):
    """Current portfolio state carried through the overlay pipeline."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    asof: pd.Timestamp
    target_weights: dict[str, float] = Field(default_factory=dict)
    equity_fraction: float = Field(default=1.0, ge=0.0)
    regime: RegimeState = Field(default=RegimeState.BULL)
    breaker_state: CircuitBreakerState = Field(default=CircuitBreakerState.NORMAL)
    journal: list[OverlayJournalEntry] = Field(default_factory=list)


class OverlayContext(BaseModel):
    """Context window data passed to each overlay during rebalance."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    prices_window: pd.DataFrame
    volumes_window: pd.DataFrame
    index_prices_window: pd.Series
    sector_map: dict[str, str] = Field(default_factory=dict)
    equity_curve_to_date: pd.Series


__all__: list[str] = [
    "CircuitBreakerState",
    "OverlayContext",
    "OverlayJournalEntry",
    "PortfolioState",
]
