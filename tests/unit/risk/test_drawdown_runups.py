"""Unit tests for :class:`csm.risk.drawdown.DrawdownAnalyzer` run-up helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from csm.risk.drawdown import DrawdownAnalyzer


@pytest.fixture
def analyzer() -> DrawdownAnalyzer:
    return DrawdownAnalyzer()


def _series(values: list[float]) -> pd.Series:
    idx: pd.DatetimeIndex = pd.date_range(
        start="2026-01-01", periods=len(values), freq="D", tz="UTC"
    )
    return pd.Series(values, index=idx, dtype="float64")


def test_runup_episodes_empty_series(analyzer: DrawdownAnalyzer) -> None:
    df: pd.DataFrame = analyzer.runup_episodes(pd.Series([], dtype="float64"))
    assert df.empty


def test_runup_episodes_monotonic_decline_returns_empty(analyzer: DrawdownAnalyzer) -> None:
    """A strictly decreasing series has no run-ups — every point is the new trough."""
    series: pd.Series = _series([100.0, 90.0, 80.0, 70.0])
    df: pd.DataFrame = analyzer.runup_episodes(series)
    assert df.empty
    assert analyzer.max_runup(series) == 0.0
    assert analyzer.avg_runup_duration(series) == 0.0
    assert analyzer.avg_runup_pct(series) == 0.0


def test_runup_episodes_single_episode(analyzer: DrawdownAnalyzer) -> None:
    # Down then up then back down to/below the trough.
    series: pd.Series = _series([100.0, 80.0, 100.0, 120.0, 80.0])
    df: pd.DataFrame = analyzer.runup_episodes(series)
    assert len(df) == 1
    row: pd.Series = df.iloc[0]
    assert row["start"] == series.index[2]  # first bar above trough
    assert row["peak"] == series.index[3]
    assert row["end"] == series.index[4]
    assert row["height"] == pytest.approx((120.0 - 80.0) / 80.0)
    assert row["duration_days"] == 2


def test_runup_episodes_sawtooth(analyzer: DrawdownAnalyzer) -> None:
    # Trough at 80 then peaks at 90 and 100, with breakdowns to (or below) the trough.
    series: pd.Series = _series([100.0, 80.0, 90.0, 80.0, 100.0, 80.0])
    df: pd.DataFrame = analyzer.runup_episodes(series)
    assert len(df) == 2
    # First episode: 80→90→80 → height 12.5%
    assert df.iloc[0]["height"] == pytest.approx(0.125)
    # Second episode: 80→100→80 → height 25%
    assert df.iloc[1]["height"] == pytest.approx(0.25)


def test_max_runup_returns_peak_excursion(analyzer: DrawdownAnalyzer) -> None:
    series: pd.Series = _series([100.0, 80.0, 90.0, 120.0])
    # running trough = 80; peak = 120 → 50%
    assert analyzer.max_runup(series) == pytest.approx(0.5)
    assert analyzer.max_runup_pct(series) == pytest.approx(0.5)


def test_avg_runup_duration_and_pct(analyzer: DrawdownAnalyzer) -> None:
    series: pd.Series = _series([100.0, 80.0, 90.0, 80.0, 100.0, 80.0])
    duration: float = analyzer.avg_runup_duration(series)
    pct: float = analyzer.avg_runup_pct(series)
    assert duration == pytest.approx(1.0)
    assert pct == pytest.approx((0.125 + 0.25) / 2)


def test_runup_episodes_tz_aware_index_preserved(analyzer: DrawdownAnalyzer) -> None:
    series: pd.Series = _series([100.0, 80.0, 120.0, 80.0])
    df: pd.DataFrame = analyzer.runup_episodes(series)
    assert pd.Timestamp(df.iloc[0]["start"]).tz is not None


def test_recovery_periods_still_works(analyzer: DrawdownAnalyzer) -> None:
    """Sanity check that the original drawdown logic was not disturbed."""
    series: pd.Series = _series([100.0, 80.0, 90.0, 100.0])
    df: pd.DataFrame = analyzer.recovery_periods(series)
    assert len(df) == 1
    assert df.iloc[0]["depth"] == pytest.approx(-0.2)
