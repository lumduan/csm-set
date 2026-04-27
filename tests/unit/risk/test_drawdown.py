"""Unit tests for DrawdownAnalyzer."""

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
    def test_underwater_curve_all_zeros_for_monotonic(
        self, analyzer: DrawdownAnalyzer
    ) -> None:
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

    def test_recovery_periods_empty_for_monotonic(
        self, analyzer: DrawdownAnalyzer
    ) -> None:
        """A monotonically increasing series produces no drawdown episodes."""
        equity = _series([100.0, 110.0, 120.0])
        result = analyzer.recovery_periods(equity)
        assert result.empty

    def test_recovery_periods_single_known_episode(
        self, analyzer: DrawdownAnalyzer
    ) -> None:
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
