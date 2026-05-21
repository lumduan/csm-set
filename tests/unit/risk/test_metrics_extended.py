"""Unit tests for trade-based metrics in :mod:`csm.risk.trade_metrics`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from csm.execution.trade_pairing import ClosedTrade
from csm.risk.trade_metrics import (
    avg_bars_in_losing_trades,
    avg_bars_in_trades,
    avg_bars_in_winning_trades,
    avg_losing_trade,
    avg_winning_trade,
    expected_payoff,
    gross_loss,
    gross_profit,
    largest_losing_trade,
    largest_winning_trade,
    longest_losing_streak,
    longest_winning_streak,
    net_pnl,
    outliers_count,
    outliers_pnl,
    pct_profitable,
    profit_factor,
    ratio_avg_win_avg_loss,
)


def _t(
    pnl: str,
    *,
    bars: int = 10,
    symbol: str = "DELTA",
    side: str = "LONG",
) -> ClosedTrade:
    return ClosedTrade(
        symbol=symbol,
        side="LONG" if side == "LONG" else "SHORT",
        entry_time=datetime(2026, 1, 1, tzinfo=UTC),
        exit_time=datetime(2026, 1, 1 + bars, tzinfo=UTC),
        entry_price=Decimal("100"),
        exit_price=Decimal("110") if Decimal(pnl) > 0 else Decimal("90"),
        qty=Decimal("1"),
        realized_pnl=Decimal(pnl),
        duration_bars=bars,
        commission=Decimal("0"),
    )


@pytest.fixture
def mixed_trades() -> list[ClosedTrade]:
    """Three winners (10, 20, 30) and two losers (-5, -15)."""
    return [
        _t("10", bars=3),
        _t("-5", bars=2),
        _t("20", bars=4),
        _t("-15", bars=6),
        _t("30", bars=8),
    ]


def test_empty_inputs_return_zero() -> None:
    assert gross_profit([]) == Decimal("0")
    assert gross_loss([]) == Decimal("0")
    assert net_pnl([]) == Decimal("0")
    assert profit_factor([]) == Decimal("0")
    assert expected_payoff([]) == Decimal("0")
    assert avg_winning_trade([]) == Decimal("0")
    assert avg_losing_trade([]) == Decimal("0")
    assert largest_winning_trade([]) == Decimal("0")
    assert largest_losing_trade([]) == Decimal("0")
    assert pct_profitable([]) == Decimal("0")
    assert ratio_avg_win_avg_loss([]) == Decimal("0")
    assert outliers_count([]) == 0
    assert outliers_pnl([]) == Decimal("0")
    assert avg_bars_in_trades([]) == Decimal("0")
    assert longest_winning_streak([]) == 0
    assert longest_losing_streak([]) == 0


def test_gross_profit_and_loss(mixed_trades: list[ClosedTrade]) -> None:
    assert gross_profit(mixed_trades) == Decimal("60")
    assert gross_loss(mixed_trades) == Decimal("-20")
    assert net_pnl(mixed_trades) == Decimal("40")


def test_profit_factor_normal(mixed_trades: list[ClosedTrade]) -> None:
    # 60 / 20 = 3
    assert profit_factor(mixed_trades) == Decimal("3")


def test_profit_factor_no_losses_returns_zero() -> None:
    trades: list[ClosedTrade] = [_t("10"), _t("20")]
    assert profit_factor(trades) == Decimal("0")


def test_expected_payoff(mixed_trades: list[ClosedTrade]) -> None:
    # 40 / 5 = 8
    assert expected_payoff(mixed_trades) == Decimal("8")


def test_avg_winning_and_losing(mixed_trades: list[ClosedTrade]) -> None:
    # wins: 10, 20, 30 → avg 20
    assert avg_winning_trade(mixed_trades) == Decimal("20")
    # losses: -5, -15 → avg -10
    assert avg_losing_trade(mixed_trades) == Decimal("-10")


def test_largest_winning_and_losing(mixed_trades: list[ClosedTrade]) -> None:
    assert largest_winning_trade(mixed_trades) == Decimal("30")
    assert largest_losing_trade(mixed_trades) == Decimal("-15")


def test_pct_profitable(mixed_trades: list[ClosedTrade]) -> None:
    # 3 wins out of 5
    assert pct_profitable(mixed_trades) == Decimal("3") / Decimal("5")


def test_ratio_avg_win_avg_loss(mixed_trades: list[ClosedTrade]) -> None:
    # |20| / |10| = 2
    assert ratio_avg_win_avg_loss(mixed_trades) == Decimal("2")


def test_ratio_avg_win_avg_loss_no_losses() -> None:
    trades: list[ClosedTrade] = [_t("10")]
    assert ratio_avg_win_avg_loss(trades) == Decimal("0")


def test_outliers_default_threshold() -> None:
    # 4 trades of magnitude 1, one of magnitude 100 → avg-abs ~ 20.8, cutoff 62.4
    trades: list[ClosedTrade] = [
        _t("1"),
        _t("-1"),
        _t("1"),
        _t("-1"),
        _t("100"),
    ]
    assert outliers_count(trades) == 1
    assert outliers_pnl(trades) == Decimal("100")


def test_outliers_zero_avg_returns_zero() -> None:
    """If avg-abs is zero (no realised P&L), there are no outliers."""
    trades: list[ClosedTrade] = []
    assert outliers_count(trades) == 0
    assert outliers_pnl(trades) == Decimal("0")


def test_avg_bars(mixed_trades: list[ClosedTrade]) -> None:
    # bars: 3 + 2 + 4 + 6 + 8 = 23 / 5 = 4.6
    assert avg_bars_in_trades(mixed_trades) == Decimal("23") / Decimal("5")
    # winning bars: 3 + 4 + 8 = 15 / 3 = 5
    assert avg_bars_in_winning_trades(mixed_trades) == Decimal("5")
    # losing bars: 2 + 6 = 8 / 2 = 4
    assert avg_bars_in_losing_trades(mixed_trades) == Decimal("4")


def test_winning_streak() -> None:
    trades: list[ClosedTrade] = [
        _t("1"),
        _t("1"),
        _t("-1"),
        _t("1"),
        _t("1"),
        _t("1"),
        _t("-1"),
    ]
    assert longest_winning_streak(trades) == 3
    assert longest_losing_streak(trades) == 1


def test_losing_streak() -> None:
    trades: list[ClosedTrade] = [
        _t("-1"),
        _t("-1"),
        _t("-1"),
        _t("-1"),
        _t("1"),
    ]
    assert longest_losing_streak(trades) == 4
    assert longest_winning_streak(trades) == 1


def test_zero_pnl_trade_treated_as_breakeven() -> None:
    """Trades with realized_pnl == 0 are neither wins nor losses."""
    trades: list[ClosedTrade] = [_t("10"), _t("0"), _t("-5")]
    assert pct_profitable(trades) == Decimal("1") / Decimal("3")
    # Streak resets through breakeven
    assert longest_winning_streak(trades) == 1
    assert longest_losing_streak(trades) == 1
