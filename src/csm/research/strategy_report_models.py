"""Pydantic v2 models for the per-strategy TradingView-style report.

The shapes here mirror the JSON contract documented in the umbrella
``feature-strategies-report-metrics`` ROADMAP (Phase 1 emits this; Phase 3
gateway re-parses it; Phase 4 dashboard renders it). Every monetary,
ratio, and percentage value is :class:`decimal.Decimal` end-to-end and
JSON-serialised as a string via :meth:`pydantic.BaseModel.model_dump`
with ``mode="json"``.

Optional fields default to ``None`` so strategies that do not produce
them (e.g. csm-set is daily-only, so intrabar fields are ``None``;
csm-set has no margin, so :class:`MarginUsage` fields are ``None``) can
omit them while the downstream parser still validates structurally.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PositionScope = Literal["all", "long", "short"]


class _ReportBase(BaseModel):
    """Common Pydantic config for all report sub-models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Headline(_ReportBase):
    """Top-of-page KPIs."""

    total_pnl: Decimal
    total_pnl_pct: Decimal
    max_equity_drawdown: Decimal
    max_equity_drawdown_pct: Decimal
    total_trades: int = Field(ge=0)
    profitable_trades: int = Field(ge=0)
    profitable_pct: Decimal
    profit_factor: Decimal


class ProfitStructure(_ReportBase):
    """Profit-structure bar chart values (gross totals)."""

    total_profit: Decimal
    open_pnl: Decimal
    total_loss: Decimal
    commission: Decimal
    net_pnl: Decimal


class ReturnsRow(_ReportBase):
    """One row of the returns table (per side or 'all')."""

    initial_capital: Decimal
    open_pnl: Decimal
    net_pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    profit_factor: Decimal
    commission_paid: Decimal
    expected_payoff: Decimal


class Returns(_ReportBase):
    """Returns table broken down by side."""

    all: ReturnsRow
    long: ReturnsRow
    short: ReturnsRow


class BenchmarkComparison(_ReportBase):
    """Buy-and-hold benchmark comparison summary."""

    buy_and_hold_return: Decimal
    buy_and_hold_pct: Decimal
    strategy_outperformance: Decimal


class RiskAdjusted(_ReportBase):
    """Risk-adjusted return metrics."""

    sharpe_ratio: Decimal
    sortino_ratio: Decimal


class PnLDistributionBucket(_ReportBase):
    """One bucket of the trade-return histogram."""

    bucket_low_pct: Decimal
    bucket_high_pct: Decimal
    count: int = Field(ge=0)
    kind: Literal["loss", "profit", "breakeven"]


class WinLossSplit(_ReportBase):
    """Donut-chart split of win/loss/breakeven trade counts."""

    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    breakeven: int = Field(ge=0)


class TradesAnalysis(_ReportBase):
    """Histogram + donut summary of trade outcomes."""

    pnl_distribution: list[PnLDistributionBucket] = Field(default_factory=list)
    win_loss_split: WinLossSplit
    avg_loss_pct: Decimal
    avg_profit_pct: Decimal


class DetailsRow(_ReportBase):
    """One row of the details table (per side or 'all')."""

    total_trades: int = Field(ge=0)
    total_open_trades: int = Field(ge=0)
    winning_trades: int = Field(ge=0)
    losing_trades: int = Field(ge=0)
    percent_profitable: Decimal
    avg_pnl: Decimal
    avg_winning_trade: Decimal
    avg_losing_trade: Decimal
    ratio_avg_win_avg_loss: Decimal
    largest_winning_trade: Decimal
    largest_winning_trade_pct: Decimal
    largest_winner_pct_of_gross_profit: Decimal
    largest_losing_trade: Decimal
    largest_losing_trade_pct: Decimal
    largest_loser_pct_of_gross_loss: Decimal
    outliers_count: int = Field(ge=0)
    outliers_pnl: Decimal
    avg_bars_in_trades: Decimal
    avg_bars_in_winning_trades: Decimal
    avg_bars_in_losing_trades: Decimal


class Details(_ReportBase):
    """Details table broken down by side."""

    all: DetailsRow
    long: DetailsRow
    short: DetailsRow


class CapitalUsageRow(_ReportBase):
    """One row of the capital-usage section."""

    annualized_return_cagr: Decimal
    return_on_initial_capital: Decimal
    account_size_required: Decimal
    return_on_account_size_required: Decimal
    net_profit_pct_of_largest_loss: Decimal


class MarginUsage(_ReportBase):
    """Margin-usage summary (TFEX-only; ``None`` for csm-set)."""

    avg_margin_used: Decimal | None = None
    max_margin_used: Decimal | None = None
    margin_efficiency: Decimal | None = None
    margin_calls: int | None = None


class CapitalEfficiency(_ReportBase):
    """Capital + margin usage section."""

    capital_usage: dict[PositionScope, CapitalUsageRow]
    margin_usage: MarginUsage


class RunUpRow(_ReportBase):
    """Run-up statistics — close-to-close and intrabar (intrabar may be ``None``)."""

    avg_duration_days: Decimal
    avg_runup: Decimal
    max_runup_close_to_close: Decimal
    max_runup_intrabar: Decimal | None = None
    max_runup_pct_initial_capital_intrabar: Decimal | None = None


class DrawdownRow(_ReportBase):
    """Drawdown statistics — close-to-close and intrabar (intrabar may be ``None``)."""

    avg_duration_days: Decimal
    avg_drawdown: Decimal
    max_drawdown_close_to_close: Decimal
    max_drawdown_intrabar: Decimal | None = None
    max_drawdown_pct_initial_capital_intrabar: Decimal | None = None
    return_of_max_drawdown: Decimal


class RunUpsDrawdowns(_ReportBase):
    """Aggregate run-ups + drawdowns block."""

    runups: RunUpRow
    drawdowns: DrawdownRow


class TradeLogEntry(_ReportBase):
    """One row of the paginated trade log."""

    entry_time: datetime
    exit_time: datetime
    symbol: str
    side: Literal["LONG", "SHORT"]
    qty: Decimal
    entry_price: Decimal
    exit_price: Decimal
    realized_pnl: Decimal
    duration_bars: int = Field(ge=0)
    commission: Decimal


class BenchmarkPoint(_ReportBase):
    """One sample of the benchmark equity curve."""

    date: datetime
    value: Decimal


class StrategyReport(_ReportBase):
    """Top-level TradingView-style strategy report payload."""

    as_of: datetime
    currency: str = Field(default="THB", min_length=3, max_length=8)
    initial_capital: Decimal
    headline: Headline
    profit_structure: ProfitStructure
    returns: Returns
    benchmark_comparison: BenchmarkComparison | None = None
    risk_adjusted: RiskAdjusted
    trades_analysis: TradesAnalysis
    details: Details
    capital_efficiency: CapitalEfficiency
    runups_drawdowns: RunUpsDrawdowns
    trades: list[TradeLogEntry] = Field(default_factory=list)
    benchmark_equity_curve: list[BenchmarkPoint] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def _as_of_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            msg = "StrategyReport.as_of must be tz-aware (UTC)"
            raise ValueError(msg)
        return value


__all__: list[str] = [
    "BenchmarkComparison",
    "BenchmarkPoint",
    "CapitalEfficiency",
    "CapitalUsageRow",
    "Details",
    "DetailsRow",
    "DrawdownRow",
    "Headline",
    "MarginUsage",
    "PnLDistributionBucket",
    "PositionScope",
    "ProfitStructure",
    "Returns",
    "ReturnsRow",
    "RiskAdjusted",
    "RunUpRow",
    "RunUpsDrawdowns",
    "StrategyReport",
    "TradeLogEntry",
    "TradesAnalysis",
    "WinLossSplit",
]
