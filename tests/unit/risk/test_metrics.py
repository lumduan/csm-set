"""Tests for performance metrics."""

import numpy as np
import pandas as pd
import pytest

from csm.risk.metrics import PerformanceMetrics

TZ: str = "Asia/Bangkok"


def _monthly_equity(values: list[float], start: str = "2023-01-31") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="ME", tz=TZ)
    return pd.Series(values, index=idx, dtype=float)


def test_sharpe_matches_manual_calculation() -> None:
    equity_curve: pd.Series = pd.Series(
        [100.0, 102.0, 104.0, 103.0, 107.0],
        index=pd.date_range("2024-01-31", periods=5, freq="ME", tz="Asia/Bangkok"),
    )
    metrics: dict[str, float] = PerformanceMetrics().summary(equity_curve)
    returns: pd.Series = equity_curve.pct_change().dropna()
    expected_sharpe: float = float(
        (returns.mean() * 12.0 - 0.02) / (returns.std(ddof=0) * np.sqrt(12.0))
    )
    assert metrics["sharpe"] == pytest.approx(expected_sharpe)


def test_cagr_matches_formula() -> None:
    """CAGR = (end / start)^(1/years) - 1 for a 12-period (1-year) series."""
    # 13 points → 12 monthly return periods → years = 12/12 = 1.0.
    # CAGR = (124/100)^1 - 1 = 0.24.
    values = [float(100 + 2 * i) for i in range(13)]  # 100, 102, ..., 124
    equity = _monthly_equity(values)
    metrics = PerformanceMetrics().summary(equity)
    expected_cagr = (equity.iloc[-1] / equity.iloc[0]) ** (12.0 / 12.0) - 1.0
    assert pytest.approx(metrics["cagr"], rel=1e-6) == expected_cagr


def test_sortino_higher_than_sharpe_with_small_downside_vol() -> None:
    """Sortino is higher than Sharpe when downside volatility is small relative to total vol."""
    # Series has mixed returns; the two negative returns are modest while positive returns
    # are large, making total vol >> downside vol → Sortino denominator smaller → Sortino > Sharpe.
    equity = _monthly_equity([100.0, 110.0, 105.0, 115.0, 108.0, 120.0])
    metrics = PerformanceMetrics().summary(equity)
    assert metrics["sortino"] > metrics["sharpe"]
    assert metrics["sortino"] > 0


def test_max_drawdown_is_negative() -> None:
    """max_drawdown is always ≤ 0 for any series with a drawdown."""
    equity = _monthly_equity([100.0, 90.0, 85.0, 95.0])
    metrics = PerformanceMetrics().summary(equity)
    assert metrics["max_drawdown"] <= 0.0


def test_win_rate_three_of_four_positive() -> None:
    """win_rate = 0.75 for a 5-point series with 3 positive and 1 negative return."""
    # Returns: +10%, +5%, -8%, +13% → 3/4 positive → win_rate = 0.75.
    equity = _monthly_equity([100.0, 110.0, 115.5, 106.26, 120.07])
    metrics = PerformanceMetrics().summary(equity)
    returns = equity.pct_change().dropna()
    expected_win_rate = float((returns > 0.0).mean())
    assert pytest.approx(metrics["win_rate"], rel=1e-6) == expected_win_rate
    # Confirm 3 out of 4 periods are positive.
    assert (returns > 0.0).sum() == 3


def test_empty_equity_curve_returns_zero_dict() -> None:
    """summary() returns an all-zero dict when there are not enough points for returns."""
    equity = _monthly_equity([100.0])  # 1-point series → no returns after pct_change
    metrics = PerformanceMetrics().summary(equity)
    for key, value in metrics.items():
        assert value == pytest.approx(0.0), f"Expected 0.0 for key {key!r}, got {value}"


def test_alpha_beta_absent_without_benchmark() -> None:
    """alpha and beta are not present in the metrics when no benchmark is provided."""
    equity = _monthly_equity([100.0, 105.0, 110.0, 115.0])
    metrics = PerformanceMetrics().summary(equity)
    assert "alpha" not in metrics
    assert "beta" not in metrics
    assert "information_ratio" not in metrics


def test_alpha_beta_present_with_benchmark() -> None:
    """alpha, beta, and information_ratio are present when a benchmark is provided."""
    equity = _monthly_equity([100.0, 105.0, 110.0, 115.0])
    benchmark = _monthly_equity([100.0, 103.0, 107.0, 112.0])
    metrics = PerformanceMetrics().summary(equity, benchmark=benchmark)
    assert "alpha" in metrics
    assert "beta" in metrics
    assert "information_ratio" in metrics


def test_beta_equals_one_for_identical_series() -> None:
    """β ≈ 1.0 when portfolio returns exactly equal benchmark returns."""
    equity = _monthly_equity([100.0, 105.0, 110.0, 107.0, 115.0])
    # Same series as both portfolio and benchmark → β = cov(r,r)/var(r) = 1.0.
    metrics = PerformanceMetrics().summary(equity, benchmark=equity.copy())
    assert pytest.approx(metrics["beta"], abs=1e-6) == 1.0
