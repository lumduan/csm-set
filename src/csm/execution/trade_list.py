"""Pydantic models for execution trade lists.

TradeSide, Trade, TradeList, and ExecutionResult follow the flat-field
convention established in Phase 4.3–4.6.
"""

from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class TradeSide(StrEnum):
    """Trade direction for the per-rebalance trade list."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Trade(BaseModel):
    """A single trade instruction for one symbol at one rebalance."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    side: TradeSide
    target_weight: float
    current_weight: float
    delta_weight: float
    target_shares: int
    delta_shares: int
    notional_thb: float
    expected_slippage_bps: float
    participation_rate: float
    capacity_violation: bool = False


class TradeList(BaseModel):
    """Aggregate trade list for a single rebalance date."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trades: list[Trade]
    total_turnover: float = Field(default=0.0, ge=0.0)
    total_slippage_cost_bps: float = Field(default=0.0, ge=0.0)
    n_buys: int = Field(default=0, ge=0)
    n_sells: int = Field(default=0, ge=0)
    n_holds: int = Field(default=0, ge=0)
    n_capacity_violations: int = Field(default=0, ge=0)
    asof: pd.Timestamp


class ExecutionResult(BaseModel):
    """Execution result wrapping a TradeList with post-execution state."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trade_list: TradeList
    post_execution_equity_fraction: float = Field(default=1.0, ge=0.0)


__all__: list[str] = [
    "ExecutionResult",
    "Trade",
    "TradeList",
    "TradeSide",
]
