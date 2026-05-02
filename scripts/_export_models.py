"""Pydantic data contract models for frontend-agnostic distribution payloads.

Each model carries ``schema_version: Literal["1.0"]`` and has a corresponding
``<name>.schema.json`` sidecar emitted via ``Model.model_json_schema()`` for
TypeScript type generation (``npx json-schema-to-typescript``).

None of these models contain ``open``, ``high``, ``low``, ``close``, ``volume``,
or ``adj_close`` fields — the boundary audit test enforces this.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class BacktestPeriod(BaseModel):
    """Start and end dates of the backtest window."""

    start: date
    end: date


class BacktestConfigSnapshot(BaseModel):
    """A reproducible subset of BacktestConfig fields for public distribution.

    Excludes fields that vary per-run (start_date, end_date) and nested models
    (vol_scaling_config) to keep the snapshot stable and consumer-safe.
    """

    formation_months: int
    skip_months: int
    top_quantile: float
    weight_scheme: str
    transaction_cost_bps: int
    rebalance_every_n: int
    vol_scaling_enabled: bool
    sector_max_weight: float


class BacktestMetrics(BaseModel):
    """Key annualised performance metrics.

    ``alpha``, ``beta``, and ``information_ratio`` are only available when a
    benchmark equity curve is provided to the backtest.
    """

    cagr: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    win_rate: float
    volatility: float
    alpha: float | None = None
    beta: float | None = None
    information_ratio: float | None = None


class BacktestSummary(BaseModel):
    """Top-level backtest summary — the primary distribution artefact."""

    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    backtest_period: BacktestPeriod
    config: BacktestConfigSnapshot
    metrics: BacktestMetrics


class EquityPoint(BaseModel):
    """A single point on the NAV equity curve."""

    date: date
    nav: float = Field(description="NAV indexed to 100 — never absolute prices")
    benchmark_nav: float | None = None


class EquityCurve(BaseModel):
    """Full equity curve as a list of date → NAV points."""

    schema_version: Literal["1.0"] = "1.0"
    description: str = "NAV indexed to 100. No raw price data."
    series: list[EquityPoint]


class AnnualRow(BaseModel):
    """A single year's portfolio and benchmark returns."""

    year: int
    portfolio_return: float
    benchmark_return: float | None = None


class AnnualReturns(BaseModel):
    """Year-by-year portfolio vs benchmark returns."""

    schema_version: Literal["1.0"] = "1.0"
    rows: list[AnnualRow]


class RankingEntry(BaseModel):
    """A single ranked security with signal values.

    Contains only derived signal metrics (quintile, z-score, percentile rank) —
    never raw price or return data.
    """

    symbol: str
    sector: str
    quintile: int = Field(ge=1, le=5, description="Quintile label 1–5")
    z_score: float = Field(description="Cross-sectional z-score of the signal")
    rank_pct: float = Field(ge=0.0, le=1.0, description="Percentile rank in (0, 1]")


class SignalRanking(BaseModel):
    """Cross-sectional momentum ranking for a given as-of date."""

    schema_version: Literal["1.0"] = "1.0"
    as_of: date
    description: str = "Cross-sectional momentum ranking. No raw price data."
    rankings: list[RankingEntry]


class ExportResultsConfig(BaseModel):
    """Configuration for the export pipeline."""

    notebook_dir: Path = Field(default_factory=lambda: Path("notebooks"))
    output_dir: Path = Field(default_factory=lambda: Path("results/static"))
    execute: bool = True
    timeout_s: int = Field(default=600, ge=1)
    memory_budget_mb: int = Field(default=2048, ge=0)
    only_notebooks: bool = False
    only_backtest: bool = False
    only_signals: bool = False


__all__ = [
    "AnnualReturns",
    "AnnualRow",
    "BacktestConfigSnapshot",
    "BacktestMetrics",
    "BacktestPeriod",
    "BacktestSummary",
    "EquityCurve",
    "EquityPoint",
    "ExportResultsConfig",
    "RankingEntry",
    "SignalRanking",
]
