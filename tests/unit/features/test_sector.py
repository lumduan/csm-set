"""Tests for SectorFeatures — Phase 2.3."""

import numpy as np
import pandas as pd
import pytest

from csm.features.sector import SectorFeatures

_TZ = "Asia/Bangkok"


def _make_close(n: int = 300, seed: int = 42, tz: str = _TZ) -> pd.Series:
    """Return a deterministic n-day close price Series with a tz-aware DatetimeIndex."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=tz)
    return pd.Series(
        100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, n))),
        index=dates,
        name="SYM",
    )


def _make_sector(n: int = 300, seed: int = 99, tz: str = _TZ) -> pd.Series:
    """Return a deterministic n-day sector index Series with a tz-aware DatetimeIndex."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=tz)
    return pd.Series(
        1000.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n))),
        index=dates,
        name="BANK_IDX",
    )


# ---------------------------------------------------------------------------
# Test Case 1: output schema (shape, columns, dtype)
# ---------------------------------------------------------------------------

def test_output_schema() -> None:
    close = _make_close()
    sector = _make_sector()
    t = close.index[-1]
    result = SectorFeatures().compute(
        close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t])
    )
    assert list(result.columns) == ["sector_rel_strength"]
    assert result.dtypes["sector_rel_strength"] == np.float32
    assert result.index[0] == t


# ---------------------------------------------------------------------------
# Test Case 2: sector_rel_strength == 0 when symbol equals sector
# ---------------------------------------------------------------------------

def test_zero_when_symbol_equals_sector() -> None:
    close = _make_close()
    t = close.index[-1]
    result = SectorFeatures().compute(
        close, {"BANK": close}, "BANK", pd.DatetimeIndex([t])
    )
    assert abs(float(result.at[t, "sector_rel_strength"])) < 1e-5


# ---------------------------------------------------------------------------
# Test Case 3: positive when symbol outperforms sector
# Use deterministic drift-only series — multiplying by a constant leaves log
# returns unchanged, so distinct per-day drift rates are required.
# ---------------------------------------------------------------------------

def test_positive_when_symbol_outperforms() -> None:
    n = 300
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=_TZ)
    symbol = pd.Series(
        100.0 * np.exp(np.cumsum(np.full(n, 0.003))), index=dates, name="SYM"
    )
    sector = pd.Series(
        100.0 * np.exp(np.cumsum(np.full(n, 0.0))), index=dates, name="SEC"
    )
    t = dates[-1]
    result = SectorFeatures().compute(
        symbol, {"AGRI": sector}, "AGRI", pd.DatetimeIndex([t])
    )
    assert float(result.at[t, "sector_rel_strength"]) > 0


# ---------------------------------------------------------------------------
# Test Case 4: negative when symbol underperforms sector
# ---------------------------------------------------------------------------

def test_negative_when_symbol_underperforms() -> None:
    n = 300
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=_TZ)
    symbol = pd.Series(
        100.0 * np.exp(np.cumsum(np.full(n, -0.003))), index=dates, name="SYM"
    )
    sector = pd.Series(
        100.0 * np.exp(np.cumsum(np.full(n, 0.003))), index=dates, name="SEC"
    )
    t = dates[-1]
    result = SectorFeatures().compute(
        symbol, {"FOOD": sector}, "FOOD", pd.DatetimeIndex([t])
    )
    assert float(result.at[t, "sector_rel_strength"]) < 0


# ---------------------------------------------------------------------------
# Test Case 5: NaN when sector code is missing from sector_closes
# ---------------------------------------------------------------------------

def test_nan_when_sector_missing() -> None:
    close = _make_close()
    t = close.index[-1]
    result = SectorFeatures().compute(close, {}, "BANK", pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "sector_rel_strength"]))


# ---------------------------------------------------------------------------
# Test Case 6: NaN when symbol history < _MIN_HIST
# ---------------------------------------------------------------------------

def test_nan_when_symbol_history_too_short() -> None:
    close = _make_close(200)   # 200 prices, need 253
    sector = _make_sector(300)
    t = close.index[-1]
    result = SectorFeatures().compute(
        close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t])
    )
    assert np.isnan(float(result.at[t, "sector_rel_strength"]))


# ---------------------------------------------------------------------------
# Test Case 7: NaN when sector history < _MIN_HIST
# ---------------------------------------------------------------------------

def test_nan_when_sector_history_too_short() -> None:
    close = _make_close(300)
    sector = _make_sector(200)   # 200 prices, need 253
    t = close.index[-1]
    result = SectorFeatures().compute(
        close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t])
    )
    assert np.isnan(float(result.at[t, "sector_rel_strength"]))


# ---------------------------------------------------------------------------
# Test Case 8: no look-ahead — mutating skip region (t-20..t) leaves signal unchanged
# ---------------------------------------------------------------------------

def test_no_lookahead_skip_region() -> None:
    close = _make_close(300)
    sector = _make_sector(300)
    t = close.index[270]
    ref = SectorFeatures().compute(
        close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t])
    )

    t_pos = close.index.get_loc(t)
    close_mutated = close.copy()
    close_mutated.iloc[t_pos - 20 : t_pos + 1] = 999.0   # mutate skip region

    result = SectorFeatures().compute(
        close_mutated, {"BANK": sector}, "BANK", pd.DatetimeIndex([t])
    )
    assert abs(
        float(ref.at[t, "sector_rel_strength"]) - float(result.at[t, "sector_rel_strength"])
    ) < 1e-5


# ---------------------------------------------------------------------------
# Test Case 9: matches manual calculation
# ---------------------------------------------------------------------------

def test_matches_manual_calculation() -> None:
    close = _make_close()
    sector = _make_sector()
    t = close.index[-1]
    sym_mom = float(np.log(close.iloc[-22] / close.iloc[-253]))
    sec_mom = float(np.log(sector.iloc[-22] / sector.iloc[-253]))
    expected = sym_mom - sec_mom
    result = SectorFeatures().compute(
        close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t])
    )
    assert abs(float(result.at[t, "sector_rel_strength"]) - expected) < 1e-4


# ---------------------------------------------------------------------------
# Test Case 10: multiple rebalance dates — correct NaN boundary pattern
# _MIN_HIST=253: index[251] → 252 prices → NaN; index[252] → 253 prices → finite
# ---------------------------------------------------------------------------

def test_multiple_dates_nan_pattern() -> None:
    close = _make_close(300)
    sector = _make_sector(300)
    dates = pd.DatetimeIndex([close.index[251], close.index[252], close.index[-1]])
    result = SectorFeatures().compute(close, {"BANK": sector}, "BANK", dates)
    # 252 prices — below _MIN_HIST=253 → NaN
    assert np.isnan(float(result.at[close.index[251], "sector_rel_strength"]))
    # exactly 253 prices — meets _MIN_HIST → finite
    assert not np.isnan(float(result.at[close.index[252], "sector_rel_strength"]))
    # 300 prices → finite
    assert not np.isnan(float(result.at[close.index[-1], "sector_rel_strength"]))


# ---------------------------------------------------------------------------
# Test Case 11: TypeError on non-DatetimeIndex symbol_close
# ---------------------------------------------------------------------------

def test_raises_on_non_datetime_close() -> None:
    sector = _make_sector()
    close_bad = pd.Series([100.0] * 300, index=range(300), name="SYM")
    t = sector.index[-1]
    with pytest.raises(TypeError):
        SectorFeatures().compute(
            close_bad, {"BANK": sector}, "BANK", pd.DatetimeIndex([t])
        )


# ---------------------------------------------------------------------------
# Test Case 12: TypeError on non-DatetimeIndex sector Series
# ---------------------------------------------------------------------------

def test_raises_on_non_datetime_sector() -> None:
    close = _make_close()
    sector_bad = pd.Series([1000.0] * 300, index=range(300), name="BANK_IDX")
    with pytest.raises(TypeError):
        SectorFeatures().compute(
            close, {"BANK": sector_bad}, "BANK", pd.DatetimeIndex([close.index[-1]])
        )


# ---------------------------------------------------------------------------
# Test Case 13: ValueError on duplicate symbol_close timestamps
# ---------------------------------------------------------------------------

def test_raises_on_duplicate_close() -> None:
    close = _make_close()
    sector = _make_sector()
    with pytest.raises(ValueError):
        SectorFeatures().compute(
            pd.concat([close, close.iloc[:1]]),
            {"BANK": sector}, "BANK",
            pd.DatetimeIndex([close.index[-1]])
        )


# ---------------------------------------------------------------------------
# Test Case 14: last-available-close semantics for a date beyond the series end
# A rebalance date 30 days after the last trading day sees the same hist as
# the last trading day itself, so the result must be identical.
# ---------------------------------------------------------------------------

def test_last_available_close_for_future_date() -> None:
    close = _make_close()
    sector = _make_sector()
    last_trading = close.index[-1]
    future_date = last_trading + pd.Timedelta(days=30)
    ref = SectorFeatures().compute(
        close, {"BANK": sector}, "BANK", pd.DatetimeIndex([last_trading])
    )
    result = SectorFeatures().compute(
        close, {"BANK": sector}, "BANK", pd.DatetimeIndex([future_date])
    )
    assert abs(
        float(ref.at[last_trading, "sector_rel_strength"])
        - float(result.at[future_date, "sector_rel_strength"])
    ) < 1e-5


# ---------------------------------------------------------------------------
# Test Case 15: TypeError on non-DatetimeIndex rebalance_dates
# ---------------------------------------------------------------------------

def test_raises_on_non_datetime_rebalance_dates() -> None:
    close = _make_close()
    sector = _make_sector()
    with pytest.raises(TypeError):
        SectorFeatures().compute(
            close, {"BANK": sector}, "BANK",
            [close.index[-1]]  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Test Case 16: ValueError on duplicate sector index timestamps
# ---------------------------------------------------------------------------

def test_raises_on_duplicate_sector_timestamps() -> None:
    close = _make_close()
    sector = _make_sector()
    with pytest.raises(ValueError):
        SectorFeatures().compute(
            close,
            {"BANK": pd.concat([sector, sector.iloc[:1]])},
            "BANK",
            pd.DatetimeIndex([close.index[-1]])
        )


# ---------------------------------------------------------------------------
# Test Case 17: NaN when boundary price is non-positive or NaN
# Inject zero at the iloc[-253] start-price position — _mom_12_1 must return NaN.
# ---------------------------------------------------------------------------

def test_nan_on_invalid_boundary_price() -> None:
    close = _make_close(300)
    sector = _make_sector(300)
    t = close.index[-1]

    # Inject 0.0 at the start-price position (iloc[-253] relative to end of series)
    close_bad = close.copy()
    close_bad.iloc[-253] = 0.0

    result = SectorFeatures().compute(
        close_bad, {"BANK": sector}, "BANK", pd.DatetimeIndex([t])
    )
    assert np.isnan(float(result.at[t, "sector_rel_strength"]))
