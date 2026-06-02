"""Unit tests for :func:`csm.research.strategy_report.build_strategy_report`."""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from csm.execution.trade_pairing import ClosedTrade
from csm.research.exceptions import ReportError
from csm.research.strategy_report import build_strategy_report
from csm.research.strategy_report_models import StrategyReport


def _trade(
    *,
    symbol: str = "DELTA",
    side: str = "LONG",
    entry_day: int = 1,
    exit_day: int = 10,
    entry_price: str = "100",
    exit_price: str = "110",
    qty: str = "10",
    pnl: str = "100",
    commission: str = "0",
) -> ClosedTrade:
    return ClosedTrade(
        symbol=symbol,
        side="LONG" if side == "LONG" else "SHORT",
        entry_time=datetime(2026, 1, entry_day, tzinfo=UTC),
        exit_time=datetime(2026, 1, exit_day, tzinfo=UTC),
        entry_price=Decimal(entry_price),
        exit_price=Decimal(exit_price),
        qty=Decimal(qty),
        realized_pnl=Decimal(pnl),
        duration_bars=exit_day - entry_day,
        commission=Decimal(commission),
    )


def _equity(values: list[float]) -> pd.Series:
    idx: pd.DatetimeIndex = pd.date_range("2026-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx, dtype="float64", name="equity")


@pytest.fixture
def small_trades() -> list[ClosedTrade]:
    return [
        _trade(entry_day=1, exit_day=3, pnl="100", commission="1"),
        _trade(entry_day=4, exit_day=6, pnl="-50", commission="1"),
        _trade(entry_day=7, exit_day=10, pnl="200", commission="1"),
    ]


def test_empty_equity_raises() -> None:
    with pytest.raises(ReportError):
        build_strategy_report(
            trades=[],
            equity=pd.Series([], dtype="float64"),
            initial_capital=Decimal("100000"),
            as_of=datetime(2026, 5, 1, tzinfo=UTC),
        )


def test_naive_as_of_raises() -> None:
    with pytest.raises(ReportError):
        build_strategy_report(
            trades=[],
            equity=_equity([100000.0]),
            initial_capital=Decimal("100000"),
            as_of=datetime(2026, 5, 1),  # naive
        )


def test_empty_trades_produces_zero_headline() -> None:
    report: StrategyReport = build_strategy_report(
        trades=[],
        equity=_equity([100000.0, 102000.0, 101000.0]),
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    assert report.headline.total_trades == 0
    assert report.headline.profitable_trades == 0
    assert report.headline.profit_factor == Decimal("0")
    # Equity moved from 100000 to 101000 → +1000 net
    assert report.headline.total_pnl == Decimal("1000")
    assert report.headline.total_pnl_pct == Decimal("0.01")


def test_full_report_round_trips_through_json(
    small_trades: list[ClosedTrade],
) -> None:
    report: StrategyReport = build_strategy_report(
        trades=small_trades,
        equity=_equity([100000.0, 100100.0, 100050.0, 100250.0]),
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    payload: str = report.model_dump_json()
    restored: StrategyReport = StrategyReport.model_validate_json(payload)
    assert restored == report


def test_decimal_serialized_as_string(
    small_trades: list[ClosedTrade],
) -> None:
    report: StrategyReport = build_strategy_report(
        trades=small_trades,
        equity=_equity([100000.0, 100050.0, 100250.0]),
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    dumped: dict = report.model_dump(mode="json")
    assert isinstance(dumped["initial_capital"], str)
    assert isinstance(dumped["headline"]["total_pnl"], str)
    assert isinstance(dumped["risk_adjusted"]["sharpe_ratio"], str)


def test_headline_counts_winners(small_trades: list[ClosedTrade]) -> None:
    report: StrategyReport = build_strategy_report(
        trades=small_trades,
        equity=_equity([100000.0, 100250.0]),
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    assert report.headline.total_trades == 3
    assert report.headline.profitable_trades == 2
    assert report.headline.profit_factor == Decimal("300") / Decimal("50")


def test_returns_long_only_short_zero(small_trades: list[ClosedTrade]) -> None:
    report: StrategyReport = build_strategy_report(
        trades=small_trades,
        equity=_equity([100000.0, 100250.0]),
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    assert report.returns.all.gross_profit == Decimal("300")
    assert report.returns.all.gross_loss == Decimal("-50")
    assert report.returns.long.gross_profit == Decimal("300")
    assert report.returns.short.gross_profit == Decimal("0")


def test_benchmark_section_included_when_benchmark_supplied(
    small_trades: list[ClosedTrade],
) -> None:
    equity: pd.Series = _equity([100000.0, 110000.0])
    benchmark: pd.Series = _equity([100000.0, 105000.0])
    report: StrategyReport = build_strategy_report(
        trades=small_trades,
        equity=equity,
        benchmark=benchmark,
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    assert report.benchmark_comparison is not None
    assert report.benchmark_comparison.buy_and_hold_return == Decimal("5000")
    assert report.benchmark_comparison.strategy_outperformance == Decimal("0.05")
    assert len(report.benchmark_equity_curve) == 2


def test_pnl_distribution_buckets() -> None:
    trades: list[ClosedTrade] = [
        _trade(entry_price="100", exit_price="105", qty="10", pnl="50"),  # +5%
        _trade(entry_price="100", exit_price="98", qty="10", pnl="-20"),  # -2%
        _trade(entry_price="100", exit_price="105", qty="10", pnl="50"),  # +5%
    ]
    report: StrategyReport = build_strategy_report(
        trades=trades,
        equity=_equity([100000.0, 101000.0]),
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    bucket_counts: dict[tuple[Decimal, Decimal], int] = {
        (b.bucket_low_pct, b.bucket_high_pct): b.count
        for b in report.trades_analysis.pnl_distribution
    }
    # Find the bucket containing +5%
    found_profit: bool = any(
        low <= Decimal("0.05") < high and count > 0 for (low, high), count in bucket_counts.items()
    )
    assert found_profit
    assert report.trades_analysis.win_loss_split.wins == 2
    assert report.trades_analysis.win_loss_split.losses == 1


def test_as_of_coerced_to_utc() -> None:
    from datetime import timedelta

    tz_bkk: timezone = timezone(timedelta(hours=7))
    report: StrategyReport = build_strategy_report(
        trades=[],
        equity=_equity([100000.0, 101000.0]),
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, 17, tzinfo=tz_bkk),
    )
    assert report.as_of.tzinfo is not None
    assert report.as_of.utcoffset() == UTC.utcoffset(report.as_of)


def test_capital_efficiency_populated_with_margin_none(
    small_trades: list[ClosedTrade],
) -> None:
    report: StrategyReport = build_strategy_report(
        trades=small_trades,
        equity=_equity([100000.0, 100250.0]),
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    assert report.capital_efficiency.margin_usage.avg_margin_used is None
    assert "all" in report.capital_efficiency.capital_usage


def test_runups_drawdowns_intrabar_none_for_daily(
    small_trades: list[ClosedTrade],
) -> None:
    report: StrategyReport = build_strategy_report(
        trades=small_trades,
        equity=_equity([100000.0, 100100.0, 100050.0, 100250.0]),
        initial_capital=Decimal("100000"),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    assert report.runups_drawdowns.runups.max_runup_intrabar is None
    assert report.runups_drawdowns.drawdowns.max_drawdown_intrabar is None
