"""Tests for ICAnalyzer - Pearson IC, Spearman rank IC, ICIR, decay curves, summary table."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from csm.research.ic_analysis import ICAnalyzer, ICResult

_TZ = "Asia/Bangkok"
_N_DATES = 12
_N_SYMBOLS = 15

analyzer = ICAnalyzer()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_panel(
    n_dates: int = _N_DATES,
    n_symbols: int = _N_SYMBOLS,
    signal_col: str = "mom_12_1",
    fwd_col: str = "fwd_ret_1m",
    seed: int = 42,
) -> pd.DataFrame:
    """Panel with noisy signal (high but imperfect IC expected)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-31", periods=n_dates, freq="ME", tz=_TZ)
    symbols = [f"SET:S{i:02d}" for i in range(n_symbols)]
    idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])
    signal = rng.standard_normal(len(idx)).astype("float32")
    noise = rng.standard_normal(len(idx)) * 0.1
    fwd_ret = (signal + noise).astype("float32")
    return pd.DataFrame({signal_col: signal, fwd_col: fwd_ret}, index=idx)


def _make_perfect_panel(
    n_dates: int = _N_DATES,
    n_symbols: int = _N_SYMBOLS,
) -> pd.DataFrame:
    """Panel where signal == fwd_ret_1m exactly (IC = 1.0 per date)."""
    rng = np.random.default_rng(99)
    dates = pd.date_range("2023-01-31", periods=n_dates, freq="ME", tz=_TZ)
    symbols = [f"SET:S{i:02d}" for i in range(n_symbols)]
    idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])
    signal = rng.standard_normal(len(idx)).astype("float64")
    return pd.DataFrame({"mom_12_1": signal, "fwd_ret_1m": signal}, index=idx)


# ---------------------------------------------------------------------------
# Test 1: IC = 1.0 on perfect synthetic signal
# ---------------------------------------------------------------------------


def test_compute_ic_perfect_signal_returns_one() -> None:
    panel = _make_perfect_panel()
    ic = analyzer.compute_ic(panel, "mom_12_1", "fwd_ret_1m")
    assert not ic.isna().any(), "no NaN expected on perfect signal with 15 symbols"
    assert (ic > 0.9999).all(), f"expected IC ≈ 1.0 on perfect signal; got {ic.min():.4f}"


# ---------------------------------------------------------------------------
# Test 2: IC values in [-1, 1]
# ---------------------------------------------------------------------------


def test_compute_ic_values_in_valid_range() -> None:
    panel = _make_panel()
    ic = analyzer.compute_ic(panel, "mom_12_1", "fwd_ret_1m")
    valid = ic.dropna()
    assert (valid >= -1.0).all() and (valid <= 1.0).all(), "IC must be in [-1, 1]"


# ---------------------------------------------------------------------------
# Test 3: NaN when fewer than 10 symbols on a date
# ---------------------------------------------------------------------------


def test_compute_ic_nan_for_small_cross_section() -> None:
    panel = _make_panel(n_dates=12, n_symbols=15)
    # Overwrite first date with only 5 non-NaN symbols
    dates = panel.index.get_level_values("date").unique()
    first_date = dates[0]
    small_symbols = [f"SET:S{i:02d}" for i in range(5, 15)]
    mask = (panel.index.get_level_values("date") == first_date) & (
        panel.index.get_level_values("symbol").isin(small_symbols)
    )
    panel = panel.copy()
    panel.loc[mask, "mom_12_1"] = float("nan")

    ic = analyzer.compute_ic(panel, "mom_12_1", "fwd_ret_1m")
    assert math.isnan(ic[first_date]), "IC should be NaN when fewer than 10 valid symbols"
    assert not ic.drop(index=first_date).isna().any(), "other dates should not be affected"


# ---------------------------------------------------------------------------
# Test 4: Spearman rank IC differs from Pearson on non-linear data
# ---------------------------------------------------------------------------


def test_compute_rank_ic_differs_from_pearson_on_nonlinear_data() -> None:
    """When signal is the sign of the return, Spearman captures the monotone
    relationship better than Pearson for at least one date."""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2023-01-31", periods=_N_DATES, freq="ME", tz=_TZ)
    symbols = [f"SET:S{i:02d}" for i in range(_N_SYMBOLS)]
    idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])
    fwd_ret = rng.standard_normal(len(idx)).astype("float64")
    signal = np.sign(fwd_ret)  # binary signal: +1/-1
    panel = pd.DataFrame({"signal": signal, "fwd_ret_1m": fwd_ret}, index=idx)

    ic = analyzer.compute_ic(panel, "signal", "fwd_ret_1m")
    rank_ic = analyzer.compute_rank_ic(panel, "signal", "fwd_ret_1m")
    # Spearman IC should be higher (closer to 1) for at least some dates
    # because the sign signal is perfectly monotone-informative
    valid_ic = ic.dropna()
    valid_rank_ic = rank_ic.dropna()
    assert valid_rank_ic.mean() > valid_ic.mean(), (
        "Spearman IC should be higher than Pearson IC for a binary sign signal"
    )


# ---------------------------------------------------------------------------
# Test 5: ICIR matches manual mean/std calculation
# ---------------------------------------------------------------------------


def test_compute_icir_matches_manual_formula() -> None:
    ic_vals = pd.Series([0.05, 0.10, -0.02, 0.08, 0.12, 0.03, 0.07, 0.09, -0.01, 0.06, 0.11, 0.04])
    expected = float(ic_vals.mean() / ic_vals.std(ddof=1))
    result = analyzer.compute_icir(ic_vals)
    assert abs(result - expected) < 1e-10, f"ICIR={result} != expected={expected}"


# ---------------------------------------------------------------------------
# Test 6: ICIR returns NaN when fewer than 12 periods
# ---------------------------------------------------------------------------


def test_compute_icir_nan_for_short_series() -> None:
    short_ic = pd.Series([0.05, 0.10, 0.08, 0.03, 0.07, 0.09, 0.06, 0.11, 0.04, 0.02, 0.12])
    assert len(short_ic) == 11  # one short of the 12-period minimum
    assert math.isnan(analyzer.compute_icir(short_ic)), "ICIR should be NaN for < 12 periods"


def test_compute_icir_valid_at_exactly_12_periods() -> None:
    ic_vals = pd.Series([0.05, 0.10, -0.02, 0.08, 0.12, 0.03, 0.07, 0.09, -0.01, 0.06, 0.11, 0.04])
    assert len(ic_vals) == 12
    result = analyzer.compute_icir(ic_vals)
    assert not math.isnan(result), "ICIR should be valid at exactly 12 periods"


# ---------------------------------------------------------------------------
# Test 7: Decay curve returns correct horizon index
# ---------------------------------------------------------------------------


def test_compute_decay_curve_index_matches_horizons() -> None:
    panel = _make_panel()
    # Add additional forward return columns to enable multi-horizon decay
    panel = panel.copy()
    panel["fwd_ret_3m"] = panel["fwd_ret_1m"] * 1.1
    panel["fwd_ret_6m"] = panel["fwd_ret_1m"] * 1.2

    curve = analyzer.compute_decay_curve(panel, "mom_12_1", [1, 3, 6])
    assert list(curve.index) == [1, 3, 6], f"expected horizons [1,3,6]; got {list(curve.index)}"


def test_compute_decay_curve_nan_for_missing_horizon_column() -> None:
    panel = _make_panel()  # only has fwd_ret_1m
    curve = analyzer.compute_decay_curve(panel, "mom_12_1", [1, 2])
    assert not math.isnan(curve[1]), "horizon 1 column exists; should not be NaN"
    assert math.isnan(curve[2]), "horizon 2 column absent; should be NaN"


# ---------------------------------------------------------------------------
# Test 8: Decay curve value = mean IC from compute_ic
# ---------------------------------------------------------------------------


def test_compute_decay_curve_value_equals_mean_ic() -> None:
    panel = _make_panel()
    ic_series = analyzer.compute_ic(panel, "mom_12_1", "fwd_ret_1m")
    expected_mean = float(ic_series.mean())

    curve = analyzer.compute_decay_curve(panel, "mom_12_1", [1])
    assert abs(curve[1] - expected_mean) < 1e-9, (
        f"decay_curve[1]={curve[1]} != mean IC={expected_mean}"
    )


# ---------------------------------------------------------------------------
# Test 9: summary_table columns and index shape
# ---------------------------------------------------------------------------


def test_summary_table_columns_and_shape() -> None:
    panel = _make_panel()
    table = analyzer.summary_table(panel, ["mom_12_1"])
    assert list(table.columns) == ["Mean_IC", "Std_IC", "ICIR", "t_stat", "pct_positive"]
    assert table.index.tolist() == ["mom_12_1"]


def test_summary_table_multiple_signals() -> None:
    panel = _make_panel()
    panel = panel.copy()
    panel["mom_6_1"] = panel["mom_12_1"] * 0.8
    table = analyzer.summary_table(panel, ["mom_12_1", "mom_6_1"])
    assert table.shape[0] == 2
    assert set(table.index) == {"mom_12_1", "mom_6_1"}


# ---------------------------------------------------------------------------
# Test 10: t_stat = ICIR * sqrt(T)
# ---------------------------------------------------------------------------


def test_summary_table_t_stat_equals_icir_times_sqrt_t() -> None:
    panel = _make_panel()
    table = analyzer.summary_table(panel, ["mom_12_1"])
    ic_s = analyzer.compute_ic(panel, "mom_12_1", "fwd_ret_1m")
    valid = ic_s.dropna()
    icir = analyzer.compute_icir(ic_s)
    expected_t = icir * math.sqrt(len(valid))
    actual_t = float(table.loc["mom_12_1", "t_stat"])
    assert abs(actual_t - expected_t) < 1e-9, f"t_stat={actual_t} != ICIR*sqrt(T)={expected_t}"


# ---------------------------------------------------------------------------
# Test 11: Input validation — TypeError for non-DataFrame
# ---------------------------------------------------------------------------


def test_compute_ic_raises_type_error_for_non_dataframe() -> None:
    with pytest.raises(TypeError, match="pd.DataFrame"):
        analyzer.compute_ic("not_a_df", "signal", "fwd_ret_1m")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="pd.DataFrame"):
        analyzer.compute_rank_ic(42, "signal", "fwd_ret_1m")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="pd.Series"):
        analyzer.compute_icir([0.1, 0.2, 0.3])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 12: Input validation — ValueError for flat index
# ---------------------------------------------------------------------------


def test_compute_ic_raises_value_error_for_flat_index() -> None:
    flat = pd.DataFrame({"mom_12_1": [1.0, 2.0], "fwd_ret_1m": [0.1, 0.2]})
    with pytest.raises(ValueError, match="MultiIndex"):
        analyzer.compute_ic(flat, "mom_12_1", "fwd_ret_1m")


def test_compute_ic_raises_value_error_for_wrong_index_names() -> None:
    dates = pd.date_range("2023-01-31", periods=2, freq="ME", tz=_TZ)
    syms = ["A", "B"]
    idx = pd.MultiIndex.from_product([dates, syms], names=["dt", "sym"])
    df = pd.DataFrame({"mom_12_1": [1.0] * 4, "fwd_ret_1m": [0.1] * 4}, index=idx)
    with pytest.raises(ValueError, match="date.*symbol"):
        analyzer.compute_ic(df, "mom_12_1", "fwd_ret_1m")


# ---------------------------------------------------------------------------
# Test 13: Input validation — ValueError for missing column
# ---------------------------------------------------------------------------


def test_compute_ic_raises_value_error_for_missing_column() -> None:
    panel = _make_panel()
    with pytest.raises(ValueError, match="not found in panel_df"):
        analyzer.compute_ic(panel, "nonexistent", "fwd_ret_1m")

    with pytest.raises(ValueError, match="not found in panel_df"):
        analyzer.compute_ic(panel, "mom_12_1", "nonexistent_ret")


def test_summary_table_raises_for_missing_fwd_col() -> None:
    panel = _make_panel()  # only has fwd_ret_1m; no fwd_ret_2m
    with pytest.raises(ValueError, match="fwd_ret_2m"):
        analyzer.summary_table(panel, ["mom_12_1"], horizon=2)


# ---------------------------------------------------------------------------
# Test 14: ICResult dataclass is importable and constructible
# ---------------------------------------------------------------------------


def test_icresult_dataclass_structure() -> None:
    panel = _make_panel()
    ic_s = analyzer.compute_ic(panel, "mom_12_1", "fwd_ret_1m")
    rank_ic_s = analyzer.compute_rank_ic(panel, "mom_12_1", "fwd_ret_1m")
    icir = analyzer.compute_icir(ic_s)
    rank_icir = analyzer.compute_icir(rank_ic_s)
    valid = ic_s.dropna()
    result = ICResult(
        signal_name="mom_12_1",
        ic_series=ic_s,
        rank_ic_series=rank_ic_s,
        icir=icir,
        rank_icir=rank_icir,
        mean_ic=float(valid.mean()),
        std_ic=float(valid.std(ddof=1)),
        t_stat=icir * math.sqrt(len(valid)),
        pct_positive=float((valid > 0).mean()),
        decay_curve=analyzer.compute_decay_curve(panel, "mom_12_1", [1]),
    )
    assert result.signal_name == "mom_12_1"
    assert isinstance(result.ic_series, pd.Series)
    assert not math.isnan(result.icir)
