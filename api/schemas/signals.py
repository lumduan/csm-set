"""Signal ranking response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SignalRow(BaseModel):
    """A single ranked security with signal values.

    Feature columns (mom_12_1, sharpe_momentum, etc.) and rank/quintile
    columns are accepted as extra fields — the structure varies by signal set.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    symbol: str = Field(description="Ticker symbol (e.g. SET:AOT)")


class SignalRanking(BaseModel):
    """Cross-sectional signal ranking for a given as-of date."""

    model_config = ConfigDict(frozen=True)

    as_of: str = Field(description="Ranking date (YYYY-MM-DD)")
    rankings: list[SignalRow] = Field(description="Per-symbol ranking rows")
