"""Unit tests for DrawdownAnalyzer."""

import numpy as np
import pandas as pd
import pytest

from csm.risk.drawdown import DrawdownAnalyzer

TZ: str = "Asia/Bangkok"


def _series(values: list[float], start: str = "2023-01-31") -> pd.Series:
    """Create a monthly equity curve Series with tz-aware DatetimeIndex."""
    idx = pd.date_range(start, periods=len(values), freq="ME", tz=TZ)
    return pd.Series(values, index=idx, dtype=float)


@pytest.fixture
def analyzer() -> DrawdownAnalyzer:
    return DrawdownAnalyzer()


class TestDrawdownAnalyzer:
    def test_underwater_curve_all_zeros_for_monotonic(self, analyzer: DrawdownAnalyzer) -> None:
        """A monotonically increasing equity curve produces a flat zero underwater curve."""
        equity = _series([100.0, 110.0, 120.0, 130.0])
        underwater = analyzer.underwater_curve(equity)
        assert (underwater == 0.0).all()

    def test_max_drawdown_matches_formula(self, analyzer: DrawdownAnalyzer) -> None:
        """max_drawdown equals -(peak - trough) / peak for a known series."""
        # Peak at 100, trough at 80 → drawdown = (80-100)/100 = -0.20.
        equity = _series([100.0, 80.0, 90.0])
        result = analyzer.max_drawdown(equity)
        assert pytest.approx(result, rel=1e-6) == -0.20

    def test_max_drawdown_is_never_positive(self, analyzer: DrawdownAnalyzer) -> None:
        """max_drawdown is always ≤ 0 for any equity curve."""
        equity = _series([100.0, 90.0, 70.0, 85.0])
        assert analyzer.max_drawdown(equity) <= 0.0

    def test_recovery_periods_empty_for_monotonic(self, analyzer: DrawdownAnalyzer) -> None:
        """A monotonically increasing series produces no drawdown episodes."""
        equity = _series([100.0, 110.0, 120.0])
        result = analyzer.recovery_periods(equity)
        assert result.empty

    def test_recovery_periods_single_known_episode(self, analyzer: DrawdownAnalyzer) -> None:
        """recovery_periods() returns correct start, trough, recovery, and depth."""
        # t0=100 (peak), t1=90 (drawdown start + trough), t2=80 (deeper trough),
        # t3=100 (recovery back to peak).
        equity = _series([100.0, 90.0, 80.0, 100.0])
        episodes = analyzer.recovery_periods(equity)

        assert len(episodes) == 1
        row = episodes.iloc[0]
        dates = equity.index

        assert row["start"] == dates[1]
        assert row["trough"] == dates[2]
        assert row["recovery"] == dates[3]
        assert pytest.approx(row["depth"], rel=1e-6) == -0.20

    def test_duration_days_consistent_with_recovery_minus_start(
        self, analyzer: DrawdownAnalyzer
    ) -> None:
        """duration_days equals (recovery - start).days for every episode."""
        equity = _series([100.0, 85.0, 80.0, 100.0, 95.0, 100.0])
        episodes = analyzer.recovery_periods(equity)

        assert not episodes.empty
        for _, row in episodes.iterrows():
            expected_days = int((row["recovery"] - row["start"]).days)
            assert row["duration_days"] == expected_days

    def test_recovery_periods_open_episode_not_included(self, analyzer: DrawdownAnalyzer) -> None:
        """An episode that has not recovered by end of series is excluded from the table."""
        equity = _series([100.0, 90.0, 80.0])
        episodes = analyzer.recovery_periods(equity)
        assert episodes.empty

    def test_recovery_periods_multiple_episodes_count(self, analyzer: DrawdownAnalyzer) -> None:
        """recovery_periods() returns one row per complete episode."""
        equity = _series([100.0, 85.0, 80.0, 100.0, 95.0, 100.0])
        episodes = analyzer.recovery_periods(equity)
        assert len(episodes) == 2

    def test_max_drawdown_single_point_returns_zero(self, analyzer: DrawdownAnalyzer) -> None:
        """A single-point equity curve has no drawdown."""
        equity = _series([100.0])
        assert analyzer.max_drawdown(equity) == 0.0

    def test_recovery_periods_includes_recovery_months_column(
        self, analyzer: DrawdownAnalyzer
    ) -> None:
        """recovery_periods() output always contains a recovery_months column."""
        equity = _series([100.0, 80.0, 100.0])
        episodes = analyzer.recovery_periods(equity)
        assert "recovery_months" in episodes.columns

    def test_recovery_months_consistent_with_duration_days(
        self, analyzer: DrawdownAnalyzer
    ) -> None:
        """recovery_months == round(duration_days / 30.5, 1) for every episode."""
        equity = _series([100.0, 85.0, 80.0, 100.0])
        episodes = analyzer.recovery_periods(equity)
        assert len(episodes) == 1
        row = episodes.iloc[0]
        expected = round(row["duration_days"] / 30.5, 1)
        assert row["recovery_months"] == pytest.approx(expected, rel=1e-6)

    def test_recovery_months_positive_for_completed_episode(
        self, analyzer: DrawdownAnalyzer
    ) -> None:
        """recovery_months is strictly positive for every completed episode."""
        equity = _series([100.0, 80.0, 70.0, 100.0, 90.0, 100.0])
        episodes = analyzer.recovery_periods(equity)
        assert (episodes["recovery_months"] > 0).all()


# ---------------------------------------------------------------------------
# TestRollingDrawdown
# ---------------------------------------------------------------------------


class TestRollingDrawdown:
    """Tests for DrawdownAnalyzer.rolling_drawdown()."""

    def test_monotonic_equity_zero_dd(self, analyzer: DrawdownAnalyzer) -> None:
        """Monotonically increasing equity produces flat 0.0 rolling DD."""
        equity = _series([100.0, 110.0, 120.0, 130.0, 140.0])
        result = analyzer.rolling_drawdown(equity, window=3)
        assert (result == 0.0).all()

    def test_known_drop_and_recovery(self, analyzer: DrawdownAnalyzer) -> None:
        """Equity 100 → 80 → 100 with window=3 produces expected DD values."""
        equity = _series([100.0, 80.0, 100.0])
        result = analyzer.rolling_drawdown(equity, window=3)
        assert len(result) == 3
        assert result.iloc[0] == pytest.approx(0.0)
        assert result.iloc[1] == pytest.approx(80.0 / 100.0 - 1.0)
        assert result.iloc[2] == pytest.approx(100.0 / 100.0 - 1.0)

    def test_recovers_as_window_rolls(self, analyzer: DrawdownAnalyzer) -> None:
        """DD recovers to 0 once the trough rolls out of the window."""
        # 100 bars: rise from 100 to 200 over first 50, crash to 100 on day 51,
        # then flat at 100 for days 52-100
        values = np.empty(100)
        values[0] = 100.0
        for i in range(1, 51):
            values[i] = values[i - 1] * 1.01  # rising
        values[51] = 100.0  # crash
        values[52:] = 100.0  # flat
        equity = _series(values.tolist())

        result = analyzer.rolling_drawdown(equity, window=20)
        # After the crash, DD should be strongly negative
        assert result.iloc[51] < -0.30
        # 20 bars after crash, trough rolls out → DD = 0
        assert result.iloc[71] == pytest.approx(0.0)

    def test_empty_returns_empty(self, analyzer: DrawdownAnalyzer) -> None:
        """Empty input returns empty Series."""
        equity = pd.Series(dtype=float)
        result = analyzer.rolling_drawdown(equity, window=60)
        assert result.empty

    def test_short_history_vs_window(self, analyzer: DrawdownAnalyzer) -> None:
        """With min_periods=1, short history still produces valid results."""
        equity = _series([100.0, 95.0, 90.0])
        result = analyzer.rolling_drawdown(equity, window=60)
        assert len(result) == 3
        # Each value is relative to running peak with whatever history is available
        assert result.iloc[0] == 0.0  # first point is its own peak
        assert result.iloc[1] == pytest.approx(95.0 / 100.0 - 1.0)
        assert result.iloc[2] == pytest.approx(90.0 / 100.0 - 1.0)
