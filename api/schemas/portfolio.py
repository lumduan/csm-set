"""Portfolio response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Holding(BaseModel):
    """A single portfolio holding."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(description="Ticker symbol (e.g. SET:AOT)")
    weight: float = Field(ge=0.0, le=1.0, description="Portfolio weight fraction")
    sector: str | None = Field(default=None, description="Sector classification code")


class PortfolioSnapshot(BaseModel):
    """Current portfolio state with holdings and summary metrics.

    In public mode, holdings may be empty and summary_metrics are populated
    from the pre-computed backtest summary JSON.  In private mode, holdings
    come from the live portfolio state.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    as_of: str = Field(description="Snapshot timestamp (ISO-8601)")
    holdings: list[Holding] = Field(description="Current portfolio holdings")
    summary_metrics: dict[str, float] = Field(
        default_factory=dict,
        description="Key performance metrics (CAGR, Sharpe, Sortino, etc.)",
    )
