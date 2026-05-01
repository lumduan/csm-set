"""Tests for RiskAdjustedFeatures — Phase 2.2."""

import numpy as np
import pandas as pd
import pytest

from csm.features.risk_adjusted import RiskAdjustedFeatures

_TZ = "Asia/Bangkok"


def _make_close(n: int = 400, seed: int = 42, tz: str = _TZ) -> pd.Series:
    """Deterministic n-day trading-day price series for a single symbol."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=tz)
    log_rets = rng.normal(0.0005, 0.015, size=n)
    return pd.Series(100.0 * np.exp(np.cumsum(log_rets)), index=dates, name="SYM")


def _make_index(n: int = 400, seed: int = 99, tz: str = _TZ) -> pd.Series:
    """Deterministic n-day SET index price series."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=tz)
    log_rets = rng.normal(0.0003, 0.012, size=n)
    return pd.Series(1000.0 * np.exp(np.cumsum(log_rets)), index=dates, name="SET")


# ---------------------------------------------------------------------------
# Test Case 1 — output schema: shape, columns, dtypes
# ---------------------------------------------------------------------------


def test_output_schema() -> None:
    close = _make_close()
    index = _make_index()
    t = close.index[-1]
    result = RiskAdjustedFeatures().compute(close, index, pd.DatetimeIndex([t]))
    assert list(result.columns) == ["sharpe_momentum", "residual_momentum"]
    assert list(result.index) == [t]
    assert result.dtypes["sharpe_momentum"] == np.float32
    assert result.dtypes["residual_momentum"] == np.float32


# ---------------------------------------------------------------------------
# Test Case 2 — sharpe_momentum matches manual calculation
# ---------------------------------------------------------------------------


def test_sharpe_momentum_manual() -> None:
    close = _make_close()
    index = _make_index()
    t = close.index[-1]
    # 253 prices from hist.iloc[-274:-21] -> 252 log returns -> sample std -> annualise
    prices_window = close.iloc[-274:-21].values
    daily_rets = np.diff(np.log(prices_window))
    vol = float(daily_rets.std(ddof=1)) * float(np.sqrt(252.0))
    mom12_1 = float(np.log(close.iloc[-22] / close.iloc[-253]))
    expected = mom12_1 / vol
    result = RiskAdjustedFeatures().compute(close, index, pd.DatetimeIndex([t]))
    assert abs(float(result.at[t, "sharpe_momentum"]) - expected) < 1e-4


# ---------------------------------------------------------------------------
# Test Case 3 — sharpe_momentum is NaN when vol = 0 (constant price)
# ---------------------------------------------------------------------------


def test_sharpe_nan_on_zero_vol() -> None:
    dates = pd.date_range("2021-01-04", periods=400, freq="B", tz=_TZ)
    close = pd.Series(100.0, index=dates, name="FLAT")
    t = close.index[-1]
    result = RiskAdjustedFeatures().compute(close, _make_index(), pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "sharpe_momentum"]))


# ---------------------------------------------------------------------------
# Test Case 4 — both signals NaN when len(hist) < _MIN_HIST (274)
# ---------------------------------------------------------------------------


def test_nan_when_history_too_short() -> None:
    close = _make_close(200)  # only 200 days, need 274
    index = _make_index(200)
    t = close.index[-1]
    result = RiskAdjustedFeatures().compute(close, index, pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "sharpe_momentum"]))
    assert np.isnan(float(result.at[t, "residual_momentum"]))


# ---------------------------------------------------------------------------
# Test Case 5 — residual_momentum recovers known alpha from synthetic data
# ---------------------------------------------------------------------------


def test_residual_momentum_known_alpha() -> None:
    # Zero-mean the index returns in the exact regression window so that
    # OLS intercept = mean(sym_rets_window) ≈ true_alpha, unbiased by mean(x).
    # Window for n=400, t=index[-1]: hist.iloc[-274:-21] = close[126:379] (253 prices)
    # → daily log-return positions 127..378 (0-indexed) → 252 values.
    rng = np.random.default_rng(0)
    n = 400
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=_TZ)
    true_alpha_daily = 0.0003
    true_beta = 0.7
    idx_rets = rng.normal(0.0, 0.012, n)
    idx_rets[127:379] -= idx_rets[127:379].mean()  # force zero mean in regression window
    noise = rng.normal(0.0, 0.001, n)  # low noise for tight estimate
    sym_rets = true_alpha_daily + true_beta * idx_rets + noise
    index_close = pd.Series(1000.0 * np.exp(np.cumsum(idx_rets)), index=dates, name="SET")
    close = pd.Series(100.0 * np.exp(np.cumsum(sym_rets)), index=dates, name="SYM")
    t = close.index[-1]
    result = RiskAdjustedFeatures().compute(close, index_close, pd.DatetimeIndex([t]))
    estimated = float(result.at[t, "residual_momentum"])
    expected = true_alpha_daily * 252
    # With zero-mean x, SE(intercept) = noise_std/sqrt(252) = 6.3e-5/day → 0.016 annualised.
    # Tolerance of 0.06 covers 3-sigma comfortably.
    assert abs(estimated - expected) < 0.06


# ---------------------------------------------------------------------------
# Test Case 6 — residual_momentum NaN when index history < _MIN_HIST
# ---------------------------------------------------------------------------


def test_residual_nan_when_index_too_short() -> None:
    close = _make_close(400)
    index_short = _make_index(200)  # only 200 days, need 274
    t = close.index[-1]
    result = RiskAdjustedFeatures().compute(close, index_short, pd.DatetimeIndex([t]))
    assert np.isfinite(float(result.at[t, "sharpe_momentum"]))  # unaffected
    assert np.isnan(float(result.at[t, "residual_momentum"]))


# ---------------------------------------------------------------------------
# Test Case 7 — residual_momentum NaN when index returns have zero variance
# ---------------------------------------------------------------------------


def test_residual_nan_on_zero_variance_index() -> None:
    dates = pd.date_range("2021-01-04", periods=400, freq="B", tz=_TZ)
    flat_index = pd.Series(1000.0, index=dates, name="FLAT")
    close = _make_close(400)
    t = close.index[-1]
    result = RiskAdjustedFeatures().compute(close, flat_index, pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "residual_momentum"]))


# ---------------------------------------------------------------------------
# Test Case 8 — no look-ahead: mutating skip region (t-20 to t) leaves signals unchanged
# ---------------------------------------------------------------------------


def test_no_lookahead_skip_region() -> None:
    close = _make_close(400)
    index = _make_index(400)
    t = close.index[350]
    ref = RiskAdjustedFeatures().compute(close, index, pd.DatetimeIndex([t]))

    t_pos = close.index.get_loc(t)
    close_mutated = close.copy()
    close_mutated.iloc[t_pos - 20 : t_pos + 1] = 999.0  # t-20 through t

    result = RiskAdjustedFeatures().compute(close_mutated, index, pd.DatetimeIndex([t]))
    assert abs(float(ref.at[t, "sharpe_momentum"]) - float(result.at[t, "sharpe_momentum"])) < 1e-5
    assert (
        abs(float(ref.at[t, "residual_momentum"]) - float(result.at[t, "residual_momentum"])) < 1e-5
    )


# ---------------------------------------------------------------------------
# Test Case 9 — no look-ahead: mutating index skip region leaves residual unchanged
# ---------------------------------------------------------------------------


def test_no_lookahead_index_skip_region() -> None:
    close = _make_close(400)
    index = _make_index(400)
    t = close.index[350]
    ref = RiskAdjustedFeatures().compute(close, index, pd.DatetimeIndex([t]))

    t_pos = index.index.get_loc(t)
    index_mutated = index.copy()
    index_mutated.iloc[t_pos - 20 : t_pos + 1] = 9999.0  # t-20 through t

    result = RiskAdjustedFeatures().compute(close, index_mutated, pd.DatetimeIndex([t]))
    assert (
        abs(float(ref.at[t, "residual_momentum"]) - float(result.at[t, "residual_momentum"])) < 1e-5
    )


# ---------------------------------------------------------------------------
# Test Case 10 — non-trading rebalance date uses last available close
# ---------------------------------------------------------------------------


def test_non_trading_rebalance_date() -> None:
    close = _make_close(400)
    index = _make_index(400)
    last_friday = close.index[-1]
    saturday = last_friday + pd.Timedelta(days=1)
    ref = RiskAdjustedFeatures().compute(close, index, pd.DatetimeIndex([last_friday]))
    result = RiskAdjustedFeatures().compute(close, index, pd.DatetimeIndex([saturday]))
    assert (
        abs(
            float(ref.at[last_friday, "sharpe_momentum"])
            - float(result.at[saturday, "sharpe_momentum"])
        )
        < 1e-5
    )
    assert (
        abs(
            float(ref.at[last_friday, "residual_momentum"])
            - float(result.at[saturday, "residual_momentum"])
        )
        < 1e-5
    )


# ---------------------------------------------------------------------------
# Test Case 11 — ValueError on duplicate close timestamps
# ---------------------------------------------------------------------------


def test_raises_on_duplicate_close() -> None:
    close = _make_close(400)
    index = _make_index(400)
    dup_close = pd.concat([close, close.iloc[:1]])
    with pytest.raises(ValueError):
        RiskAdjustedFeatures().compute(dup_close, index, pd.DatetimeIndex([close.index[-1]]))


# ---------------------------------------------------------------------------
# Test Case 12 — ValueError on duplicate index_close timestamps
# ---------------------------------------------------------------------------


def test_raises_on_duplicate_index_close() -> None:
    close = _make_close(400)
    index = _make_index(400)
    dup_index = pd.concat([index, index.iloc[:1]])
    with pytest.raises(ValueError):
        RiskAdjustedFeatures().compute(close, dup_index, pd.DatetimeIndex([close.index[-1]]))


# ---------------------------------------------------------------------------
# Test Case 13 — TypeError on non-DatetimeIndex close
# ---------------------------------------------------------------------------


def test_raises_on_non_datetime_close() -> None:
    close_bad = pd.Series([100.0] * 400, index=range(400), name="SYM")
    with pytest.raises(TypeError):
        RiskAdjustedFeatures().compute(
            close_bad, _make_index(), pd.DatetimeIndex([_make_close().index[-1]])
        )


# ---------------------------------------------------------------------------
# Test Case 14 — TypeError on non-DatetimeIndex index_close
# ---------------------------------------------------------------------------


def test_raises_on_non_datetime_index_close() -> None:
    index_bad = pd.Series([1000.0] * 400, index=range(400), name="SET")
    with pytest.raises(TypeError):
        RiskAdjustedFeatures().compute(
            _make_close(), index_bad, pd.DatetimeIndex([_make_close().index[-1]])
        )


# ---------------------------------------------------------------------------
# Test Case 15 — TypeError on non-DatetimeIndex rebalance_dates
# ---------------------------------------------------------------------------


def test_raises_on_non_datetime_rebalance_dates() -> None:
    with pytest.raises(TypeError):
        RiskAdjustedFeatures().compute(
            _make_close(),
            _make_index(),
            [_make_close().index[-1]],  # type: ignore
        )


# ---------------------------------------------------------------------------
# Test Case 16 — residual_momentum NaN when index has too many gaps in window
# ---------------------------------------------------------------------------


def test_residual_nan_when_index_has_too_many_gaps() -> None:
    """Removing most index dates in the regression window drops pairs below _MIN_OLS_PAIRS."""
    close = _make_close(400)
    index = _make_index(400)
    t = close.index[-1]
    # Find the dates that fall inside the vol/regression window (hist.iloc[-274:-21])
    hist = close.loc[close.index <= t]
    window_dates = hist.iloc[-274:-21].index
    # Keep only every 5th date in the window -> ~50 dates, below _MIN_OLS_PAIRS (63)
    dates_to_drop = window_dates[np.arange(len(window_dates)) % 5 != 0]
    sparse_index = index.drop(dates_to_drop)
    result = RiskAdjustedFeatures().compute(close, sparse_index, pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "residual_momentum"]))


# ---------------------------------------------------------------------------
# Test Case 17 — sharpe_momentum NaN when a boundary price is non-positive
# ---------------------------------------------------------------------------


def test_sharpe_nan_on_nonpositive_boundary_price() -> None:
    close = _make_close(400)
    t = close.index[-1]
    # Zero out the formation-end boundary price (hist.iloc[-22] = price at t-21)
    close_bad = close.copy()
    close_bad.iloc[-22] = 0.0
    result = RiskAdjustedFeatures().compute(close_bad, _make_index(400), pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "sharpe_momentum"]))


# ---------------------------------------------------------------------------
# Test Case 18 — residual_momentum NaN when symbol has non-positive price in window
# ---------------------------------------------------------------------------


def test_residual_nan_on_nonpositive_symbol_price_in_window() -> None:
    close = _make_close(400)
    t = close.index[-1]
    # Zero out a price inside the regression window (hist.iloc[-274:-21])
    close_bad = close.copy()
    close_bad.iloc[-150] = 0.0
    result = RiskAdjustedFeatures().compute(close_bad, _make_index(400), pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "residual_momentum"]))


# ---------------------------------------------------------------------------
# Test Case 19 — multiple rebalance dates: NaN pattern matches history length
# ---------------------------------------------------------------------------


def test_multiple_dates_nan_pattern() -> None:
    """Dates before _MIN_HIST (274) must produce NaN; later ones must be finite."""
    close = _make_close(400)
    index = _make_index(400)
    early_t = close.index[200]  # positional index 200 < 274
    late_t = close.index[-1]  # positional index 399 >= 274
    result = RiskAdjustedFeatures().compute(close, index, pd.DatetimeIndex([early_t, late_t]))
    assert np.isnan(float(result.at[early_t, "sharpe_momentum"]))
    assert np.isnan(float(result.at[early_t, "residual_momentum"]))
    assert np.isfinite(float(result.at[late_t, "sharpe_momentum"]))
    assert np.isfinite(float(result.at[late_t, "residual_momentum"]))
