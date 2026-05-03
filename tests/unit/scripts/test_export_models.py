"""Unit tests for scripts._export_models — Pydantic data contract models."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from scripts._export_models import (
    AnnualReturns,
    AnnualRow,
    BacktestConfigSnapshot,
    BacktestMetrics,
    BacktestPeriod,
    BacktestSummary,
    EquityCurve,
    EquityPoint,
    ExportResultsConfig,
    RankingEntry,
    SignalRanking,
)

TZ_BKK = ZoneInfo("Asia/Bangkok")


# ── BacktestSummary ────────────────────────────────────────────────────


def test_backtest_summary_schema_version_default() -> None:
    model = BacktestSummary(
        generated_at=datetime(2025, 1, 15, tzinfo=TZ_BKK),
        backtest_period=BacktestPeriod(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        config=BacktestConfigSnapshot(
            formation_months=12,
            skip_months=1,
            top_quantile=0.2,
            weight_scheme="equal",
            transaction_cost_bps=15,
            rebalance_every_n=1,
            vol_scaling_enabled=True,
            sector_max_weight=0.35,
        ),
        metrics=BacktestMetrics(
            cagr=0.15,
            sharpe=1.2,
            sortino=1.8,
            calmar=0.8,
            max_drawdown=-0.25,
            win_rate=0.65,
            volatility=0.12,
        ),
    )
    assert model.schema_version == "1.0"
    assert model.metrics.alpha is None
    assert model.metrics.beta is None


def test_backtest_summary_baseline_metrics() -> None:
    """Metrics with benchmark produce optional fields."""
    model = BacktestSummary(
        generated_at=datetime(2025, 1, 15, tzinfo=TZ_BKK),
        backtest_period=BacktestPeriod(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        config=BacktestConfigSnapshot(
            formation_months=12,
            skip_months=1,
            top_quantile=0.2,
            weight_scheme="equal",
            transaction_cost_bps=15,
            rebalance_every_n=1,
            vol_scaling_enabled=True,
            sector_max_weight=0.35,
        ),
        metrics=BacktestMetrics(
            cagr=0.15,
            sharpe=1.2,
            sortino=1.8,
            calmar=0.8,
            max_drawdown=-0.25,
            win_rate=0.65,
            volatility=0.12,
            alpha=0.03,
            beta=0.85,
            information_ratio=0.5,
        ),
    )
    assert model.metrics.alpha == 0.03
    assert model.metrics.beta == 0.85
    assert model.metrics.information_ratio == 0.5


# ── EquityCurve ────────────────────────────────────────────────────────


def test_equity_curve_defaults() -> None:
    point = EquityPoint(date=date(2024, 1, 15), nav=105.0)
    model = EquityCurve(series=[point])
    assert model.schema_version == "1.0"
    assert model.description == "NAV indexed to 100. No raw price data."
    assert model.series[0].benchmark_nav is None


def test_equity_point_benchmark() -> None:
    point = EquityPoint(date=date(2024, 1, 15), nav=105.0, benchmark_nav=102.0)
    assert point.benchmark_nav == 102.0


def test_equity_curve_multiple_points() -> None:
    points = [
        EquityPoint(date=date(2024, 1, 15), nav=100.0),
        EquityPoint(date=date(2024, 2, 15), nav=105.0),
        EquityPoint(date=date(2024, 3, 15), nav=103.0),
    ]
    model = EquityCurve(series=points)
    assert len(model.series) == 3


# ── AnnualReturns ──────────────────────────────────────────────────────


def test_annual_returns_no_benchmark() -> None:
    row = AnnualRow(year=2024, portfolio_return=0.15)
    model = AnnualReturns(rows=[row])
    assert model.schema_version == "1.0"
    assert model.rows[0].benchmark_return is None


def test_annual_returns_with_benchmark() -> None:
    row = AnnualRow(year=2024, portfolio_return=0.15, benchmark_return=0.08)
    model = AnnualReturns(rows=[row])
    assert model.rows[0].benchmark_return == 0.08


def test_annual_returns_multiple_years() -> None:
    rows = [
        AnnualRow(year=2023, portfolio_return=0.20, benchmark_return=0.12),
        AnnualRow(year=2024, portfolio_return=-0.05, benchmark_return=-0.03),
        AnnualRow(year=2025, portfolio_return=0.18),
    ]
    model = AnnualReturns(rows=rows)
    assert len(model.rows) == 3
    assert model.rows[2].benchmark_return is None


# ── SignalRanking ──────────────────────────────────────────────────────


def test_signal_ranking_fields() -> None:
    entry = RankingEntry(symbol="SET001", sector="BANK", quintile=5, z_score=0.15, rank_pct=0.95)
    model = SignalRanking(as_of=date(2025, 1, 15), rankings=[entry])
    assert model.schema_version == "1.0"
    assert model.description == "Cross-sectional momentum ranking. No raw price data."
    assert model.rankings[0].symbol == "SET001"
    assert model.rankings[0].sector == "BANK"
    assert model.rankings[0].quintile == 5
    assert model.rankings[0].z_score == 0.15
    assert model.rankings[0].rank_pct == 0.95


def test_ranking_entry_quintile_bounds() -> None:
    """quintile must be 1-5."""
    RankingEntry(symbol="A", sector="X", quintile=1, z_score=0.0, rank_pct=0.5)
    RankingEntry(symbol="A", sector="X", quintile=5, z_score=0.0, rank_pct=0.5)

    with pytest.raises(ValidationError):
        RankingEntry(symbol="A", sector="X", quintile=0, z_score=0.0, rank_pct=0.5)


def test_ranking_entry_rank_pct_bounds() -> None:
    """rank_pct must be 0-1."""
    RankingEntry(symbol="A", sector="X", quintile=1, z_score=0.0, rank_pct=0.0)
    RankingEntry(symbol="A", sector="X", quintile=1, z_score=0.0, rank_pct=1.0)

    with pytest.raises(ValidationError):
        RankingEntry(symbol="A", sector="X", quintile=1, z_score=0.0, rank_pct=1.1)


def test_signal_ranking_multiple_entries() -> None:
    entries = [
        RankingEntry(symbol="SET001", sector="BANK", quintile=5, z_score=0.15, rank_pct=0.95),
        RankingEntry(symbol="SET002", sector="TECH", quintile=4, z_score=0.08, rank_pct=0.72),
        RankingEntry(symbol="SET003", sector="ENERGY", quintile=3, z_score=0.03, rank_pct=0.48),
    ]
    model = SignalRanking(as_of=date(2025, 1, 15), rankings=entries)
    assert len(model.rankings) == 3


# ── ExportResultsConfig ────────────────────────────────────────────────


def test_export_results_config_defaults() -> None:
    config = ExportResultsConfig()
    assert config.output_dir == Path("results/static")
    assert config.notebook_dir == Path("notebooks")
    assert config.timeout_s == 600
    assert config.execute is True
    assert config.memory_budget_mb == 2048
    assert config.only_notebooks is False
    assert config.only_backtest is False
    assert config.only_signals is False


def test_export_results_config_custom() -> None:
    config = ExportResultsConfig(
        notebook_dir=Path("custom_nbs"),
        output_dir=Path("custom_out"),
        timeout_s=300,
        memory_budget_mb=1024,
        only_backtest=True,
    )
    assert config.notebook_dir == Path("custom_nbs")
    assert config.output_dir == Path("custom_out")
    assert config.timeout_s == 300
    assert config.memory_budget_mb == 1024
    assert config.only_backtest is True


# ── JSON Schema generation ─────────────────────────────────────────────


def test_backtest_summary_json_schema() -> None:
    schema = BacktestSummary.model_json_schema()
    props = schema["properties"]
    assert "schema_version" in props
    assert props["schema_version"].get("const") == "1.0"
    assert "generated_at" in props
    assert "backtest_period" in props
    assert "config" in props
    assert "metrics" in props


def test_equity_curve_json_schema() -> None:
    schema = EquityCurve.model_json_schema()
    props = schema["properties"]
    assert props["schema_version"].get("const") == "1.0"
    assert "description" in props
    assert "series" in props


def test_signal_ranking_json_schema() -> None:
    schema = SignalRanking.model_json_schema()
    props = schema["properties"]
    assert props["schema_version"].get("const") == "1.0"
    assert "as_of" in props
    assert "rankings" in props


def test_ranking_entry_json_schema_constraints() -> None:
    schema = RankingEntry.model_json_schema()
    props = schema["properties"]
    assert props["quintile"]["minimum"] == 1
    assert props["quintile"]["maximum"] == 5
    assert props["rank_pct"]["minimum"] == 0.0
    assert props["rank_pct"]["maximum"] == 1.0


# ── No OHLCV fields ───────────────────────────────────────────────────


def test_models_have_no_ohlcv_fields() -> None:
    """No distribution model contains open/high/low/close/volume/adj_close fields."""
    forbidden: set[str] = {"open", "high", "low", "close", "volume", "adj_close", "adjusted_close"}
    models: list[type] = [
        BacktestSummary,
        EquityCurve,
        EquityPoint,
        AnnualReturns,
        AnnualRow,
        SignalRanking,
        RankingEntry,
        BacktestPeriod,
        BacktestConfigSnapshot,
        BacktestMetrics,
    ]
    for model_cls in models:
        schema = model_cls.model_json_schema()
        props = set(schema.get("properties", {}).keys())
        overlap = props & forbidden
        assert not overlap, f"{model_cls.__name__} has forbidden fields: {overlap}"
