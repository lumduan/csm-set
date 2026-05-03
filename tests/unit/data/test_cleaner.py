"""Unit tests for PriceCleaner — Phase 1.5."""

import numpy as np
import pandas as pd

from csm.data.cleaner import PriceCleaner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(dates: pd.DatetimeIndex, close: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame with the given close series."""
    c = pd.array(close, dtype="float64")
    return pd.DataFrame(
        {
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": np.full(len(close), 1_000_000.0),
        },
        index=dates,
    )


# ---------------------------------------------------------------------------
# Test 1 — forward_fill_gaps: fills short gap, leaves long gap tail unfilled
# ---------------------------------------------------------------------------


def test_forward_fill_gaps_fills_short_gap_leaves_long_gap() -> None:
    # 25 business-day index
    dates: pd.DatetimeIndex = pd.date_range("2024-01-01", periods=25, freq="B", tz="UTC")
    close: list[float] = [100.0] * 25

    # 3-day gap at positions 3–5 (should be fully filled with limit=5)
    close[3] = close[4] = close[5] = np.nan

    # 6-day gap at positions 12–17 (positions 12–16 filled, position 17 stays NaN)
    for i in range(12, 18):
        close[i] = np.nan

    df = _make_ohlcv(dates, close)
    result = PriceCleaner().forward_fill_gaps(df, max_gap_days=5)

    # 3-day gap must be fully filled
    assert result["close"].iloc[3:6].notna().all()

    # First 5 positions of the 6-day gap must be filled
    assert result["close"].iloc[12:17].notna().all()

    # The 6th position of the gap (index 17) must remain NaN
    assert pd.isna(result["close"].iloc[17])


# ---------------------------------------------------------------------------
# Test 2 — drop_low_coverage: drops symbol with 25% missing in one year
# ---------------------------------------------------------------------------


def test_drop_low_coverage_returns_none_for_high_missing() -> None:
    dates: pd.DatetimeIndex = pd.date_range("2024-01-01", periods=252, freq="B", tz="UTC")
    close: list[float] = [100.0] * 252

    # 25% of 252 = 63 NaN bars — exceeds the 20% allowance (50.4 bars)
    for i in range(63):
        close[i] = np.nan

    df = _make_ohlcv(dates, close)
    result = PriceCleaner().drop_low_coverage(df, min_coverage=0.80, window_years=1)

    assert result is None


# ---------------------------------------------------------------------------
# Test 3 — drop_low_coverage: keeps symbol with 15% missing
# ---------------------------------------------------------------------------


def test_drop_low_coverage_returns_df_for_acceptable_missing() -> None:
    dates: pd.DatetimeIndex = pd.date_range("2024-01-01", periods=252, freq="B", tz="UTC")
    close: list[float] = [100.0] * 252

    # 15% of 252 = ~37 NaN bars — below the 20% allowance (50.4 bars)
    for i in range(37):
        close[i] = np.nan

    df = _make_ohlcv(dates, close)
    result = PriceCleaner().drop_low_coverage(df, min_coverage=0.80, window_years=1)

    assert result is not None
    assert isinstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# Test 4 — winsorise_returns: clips extreme return outlier
# ---------------------------------------------------------------------------


def test_winsorise_returns_clips_extreme_outliers() -> None:
    dates: pd.DatetimeIndex = pd.date_range("2024-01-01", periods=100, freq="B", tz="UTC")

    # Slowly-drifting series (~0.1% daily)
    close: list[float] = [100.0 + i * 0.1 for i in range(100)]

    # Inject an 80% spike at position 50 — well beyond the 99th percentile
    close[50] = close[49] * 1.8

    df = _make_ohlcv(dates, close)
    result = PriceCleaner().winsorise_returns(df, lower=0.01, upper=0.99)

    original_return_at_50 = (close[50] - close[49]) / close[49]  # ≈ 0.80
    result_return_at_50 = float(result["close"].pct_change().iloc[50])

    assert result_return_at_50 < original_return_at_50


# ---------------------------------------------------------------------------
# Test 5 — clean: returns None when coverage check fails
# ---------------------------------------------------------------------------


def test_clean_returns_none_when_coverage_fails() -> None:
    dates: pd.DatetimeIndex = pd.date_range("2024-01-01", periods=252, freq="B", tz="UTC")
    close: list[float] = [100.0] * 252

    # 25% missing — coverage check drops the symbol
    for i in range(63):
        close[i] = np.nan

    df = _make_ohlcv(dates, close)
    assert PriceCleaner().clean(df) is None


# ---------------------------------------------------------------------------
# Test 6 — clean: applies all steps in the correct order
# ---------------------------------------------------------------------------


def test_clean_applies_steps_in_order() -> None:
    # 300-bar series: short gap filled in step 1, spike clipped in step 3,
    # and coverage check passes in step 2.
    dates: pd.DatetimeIndex = pd.date_range("2024-01-01", periods=300, freq="B", tz="UTC")
    close: list[float] = [100.0 + i * 0.1 for i in range(300)]

    # 3-day gap at positions 10–12 (should be forward-filled)
    close[10] = close[11] = close[12] = np.nan

    # 80% spike at position 150 (should be winsorised)
    close[150] = close[149] * 1.8

    df = _make_ohlcv(dates, close)
    result = PriceCleaner().clean(df)

    assert result is not None

    # Step 1 verified: short gap filled
    assert result["close"].iloc[10:13].notna().all()

    # Step 3 verified: return at spike position is well below the original 80%
    result_return_at_150 = float(result["close"].pct_change().iloc[150])
    assert result_return_at_150 < 0.8
