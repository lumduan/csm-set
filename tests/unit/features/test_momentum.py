"""Tests for MomentumFeatures — Phase 2.1."""

import numpy as np
import pandas as pd
import pytest

from csm.features.momentum import MomentumFeatures

_TZ = "Asia/Bangkok"
_SIGNAL_COLS = ["mom_12_1", "mom_6_1", "mom_3_1", "mom_1_0"]


def _make_close(n: int = 300, seed: int = 42, tz: str = _TZ) -> pd.Series:
    """Return a deterministic n-day close price Series with a tz-aware DatetimeIndex."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=tz)
    log_returns = rng.normal(0.0005, 0.02, size=n)
    prices = 100.0 * np.exp(np.cumsum(log_returns))
    return pd.Series(prices, index=dates, name="TEST")


# ---------------------------------------------------------------------------
# Test Case 1: mom_12_1 matches manual pandas calculation
# ---------------------------------------------------------------------------

def test_mom_12_1_matches_manual() -> None:
    close = _make_close(300)
    t = close.index[-1]
    result = MomentumFeatures().compute(close, pd.DatetimeIndex([t]))
    expected = float(np.log(close.iloc[-22] / close.iloc[-253]))
    assert abs(float(result.at[t, "mom_12_1"]) - expected) < 1e-5


# ---------------------------------------------------------------------------
# Test Case 2: all four signals match reference calculations
# ---------------------------------------------------------------------------

def test_all_signals_match_reference() -> None:
    close = _make_close(300)
    t = close.index[-1]
    result = MomentumFeatures().compute(close, pd.DatetimeIndex([t]))

    assert abs(float(result.at[t, "mom_12_1"]) - float(np.log(close.iloc[-22] / close.iloc[-253]))) < 1e-5
    assert abs(float(result.at[t, "mom_6_1"]) - float(np.log(close.iloc[-22] / close.iloc[-127]))) < 1e-5
    assert abs(float(result.at[t, "mom_3_1"]) - float(np.log(close.iloc[-22] / close.iloc[-64]))) < 1e-5
    assert abs(float(result.at[t, "mom_1_0"]) - float(np.log(close.iloc[-1] / close.iloc[-22]))) < 1e-5


# ---------------------------------------------------------------------------
# Test Case 3a: no look-ahead — mutating prices after t leaves all signals unchanged
# ---------------------------------------------------------------------------

def test_no_lookahead_mutation_after_t() -> None:
    close = _make_close(300)
    t = close.index[279]  # rebalance at day 280 (0-indexed: 279)
    baseline = MomentumFeatures().compute(close, pd.DatetimeIndex([t]))

    mutated = close.copy()
    mutated.iloc[280:] = mutated.iloc[280:] * 999.0  # garbage values after t
    result = MomentumFeatures().compute(mutated, pd.DatetimeIndex([t]))

    for col in _SIGNAL_COLS:
        assert float(result.at[t, col]) == pytest.approx(float(baseline.at[t, col]), rel=1e-5), col


# ---------------------------------------------------------------------------
# Test Case 3b: no look-ahead — mutating t-20..t changes mom_1_0 but not formation signals
#
# For t = close.index[279]:
#   hist has 280 prices (indices 0..279).
#   hist.iloc[-22] = close.index[258]  →  t-21
#   t-20 ... t     = close.iloc[259:280]
#   Mutating that range leaves t-21 (close.index[258]) untouched, so formation
#   signals (end price = t-21) are unchanged, while mom_1_0 (end price = t) changes.
# ---------------------------------------------------------------------------

def test_no_lookahead_skip_boundary() -> None:
    close = _make_close(300)
    t = close.index[279]

    baseline = MomentumFeatures().compute(close, pd.DatetimeIndex([t]))

    # Mutate t-20 ... t (indices 259..279), leave t-21 (index 258) untouched.
    mutated = close.copy()
    mutated.iloc[259:280] = mutated.iloc[259:280] * 3.0

    result = MomentumFeatures().compute(mutated, pd.DatetimeIndex([t]))

    # Formation signals (end price at t-21 = index 258) must be unchanged.
    for col in ["mom_12_1", "mom_6_1", "mom_3_1"]:
        assert float(result.at[t, col]) == pytest.approx(float(baseline.at[t, col]), rel=1e-5), col

    # Reversal signal (end price at t = index 279) must change.
    assert float(result.at[t, "mom_1_0"]) != pytest.approx(float(baseline.at[t, "mom_1_0"]), rel=1e-5)


# ---------------------------------------------------------------------------
# Test Case 4: NaN propagation when history shorter than lookback window
# ---------------------------------------------------------------------------

def test_nan_when_insufficient_history() -> None:
    close = _make_close(50)
    t = close.index[-1]
    result = MomentumFeatures().compute(close, pd.DatetimeIndex([t]))

    assert np.isnan(float(result.at[t, "mom_12_1"]))  # needs 253
    assert np.isnan(float(result.at[t, "mom_6_1"]))   # needs 127
    assert np.isnan(float(result.at[t, "mom_3_1"]))   # needs 64
    assert not np.isnan(float(result.at[t, "mom_1_0"]))  # needs 22, have 50


# ---------------------------------------------------------------------------
# Test Case 5: rebalance date falls on a non-trading day
# ---------------------------------------------------------------------------

def test_nontrading_rebalance_date() -> None:
    close = _make_close(300)
    last_friday = close.index[-1]

    # Find the first Saturday after last_friday.
    saturday = last_friday + pd.Timedelta(days=1)
    while saturday.dayofweek != 5:
        saturday += pd.Timedelta(days=1)
    sat_ts = pd.Timestamp(saturday.date(), tz=_TZ)

    result_sat = MomentumFeatures().compute(close, pd.DatetimeIndex([sat_ts]))
    result_fri = MomentumFeatures().compute(close, pd.DatetimeIndex([last_friday]))

    for col in _SIGNAL_COLS:
        assert float(result_sat.at[sat_ts, col]) == pytest.approx(
            float(result_fri.at[last_friday, col]), rel=1e-5
        ), col


# ---------------------------------------------------------------------------
# Test Case 6: boundary price is NaN → all signals NaN
# ---------------------------------------------------------------------------

def test_nan_boundary_price() -> None:
    close = _make_close(300)
    t = close.index[-1]
    close_with_nan = close.copy()
    close_with_nan.iloc[-22] = np.nan  # t-21 boundary used by all four signals

    result = MomentumFeatures().compute(close_with_nan, pd.DatetimeIndex([t]))
    for col in _SIGNAL_COLS:
        assert np.isnan(float(result.at[t, col])), col


# ---------------------------------------------------------------------------
# Test Case 6b: boundary price is pd.NA (nullable dtype)
# ---------------------------------------------------------------------------

def test_pd_na_boundary_price() -> None:
    close = _make_close(300)
    t = close.index[-1]
    # Convert to nullable Float64 and insert pd.NA at the t-21 boundary.
    close_nullable: pd.Series = close.astype("Float64").copy()
    close_nullable.iloc[-22] = pd.NA

    result = MomentumFeatures().compute(close_nullable, pd.DatetimeIndex([t]))
    for col in _SIGNAL_COLS:
        assert np.isnan(float(result.at[t, col])), col


# ---------------------------------------------------------------------------
# Test Case 7: boundary price is non-positive → all signals NaN
# ---------------------------------------------------------------------------

def test_nonpositive_boundary_price() -> None:
    close = _make_close(300)
    t = close.index[-1]
    close_zero = close.copy()
    close_zero.iloc[-22] = 0.0

    result = MomentumFeatures().compute(close_zero, pd.DatetimeIndex([t]))
    for col in _SIGNAL_COLS:
        assert np.isnan(float(result.at[t, col])), col


# ---------------------------------------------------------------------------
# Test Case 8: unsorted input is handled transparently
# ---------------------------------------------------------------------------

def test_unsorted_input_is_handled() -> None:
    close = _make_close(300)
    t = close.index[-1]
    reverse = close.iloc[::-1]

    result_fwd = MomentumFeatures().compute(close, pd.DatetimeIndex([t]))
    result_rev = MomentumFeatures().compute(reverse, pd.DatetimeIndex([t]))

    for col in _SIGNAL_COLS:
        assert float(result_fwd.at[t, col]) == pytest.approx(
            float(result_rev.at[t, col]), rel=1e-5
        ), col


# ---------------------------------------------------------------------------
# Test Case 9a: multiple rebalance dates preserve order and columns
# ---------------------------------------------------------------------------

def test_multiple_dates_preserve_order_and_columns() -> None:
    close = _make_close(300)
    dates = pd.DatetimeIndex([close.index[260], close.index[270], close.index[299]])

    result = MomentumFeatures().compute(close, dates)

    assert list(result.index) == list(dates)
    assert list(result.columns) == _SIGNAL_COLS
    assert result.dtypes.apply(lambda d: d == np.dtype("float32")).all()


# ---------------------------------------------------------------------------
# Test Case 9b: duplicate index raises ValueError
# ---------------------------------------------------------------------------

def test_duplicate_index_raises() -> None:
    close = _make_close(50)
    duped = pd.concat([close, close.iloc[:1]])  # append duplicate of first row

    with pytest.raises(ValueError, match="duplicate timestamps"):
        MomentumFeatures().compute(duped, pd.DatetimeIndex([close.index[-1]]))


# ---------------------------------------------------------------------------
# Regression: empty rebalance_dates returns empty frame with correct columns/dtype
# ---------------------------------------------------------------------------

def test_empty_rebalance_dates() -> None:
    close = _make_close(300)
    result = MomentumFeatures().compute(close, pd.DatetimeIndex([]))

    assert result.empty
    assert list(result.columns) == _SIGNAL_COLS
    assert result.dtypes.apply(lambda d: d == np.dtype("float32")).all()


# ---------------------------------------------------------------------------
# Type validation: non-DatetimeIndex raises TypeError
# ---------------------------------------------------------------------------

def test_non_datetime_index_raises() -> None:
    close = pd.Series([100.0, 101.0], index=[0, 1])
    with pytest.raises(TypeError, match="DatetimeIndex"):
        MomentumFeatures().compute(close, pd.DatetimeIndex([]))


def test_non_datetime_rebalance_dates_raises() -> None:
    close = _make_close(50)
    with pytest.raises(TypeError, match="DatetimeIndex"):
        MomentumFeatures().compute(close, [close.index[-1]])  # type: ignore[arg-type]
