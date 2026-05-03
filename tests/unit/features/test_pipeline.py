"""Tests for the feature pipeline."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline

_TZ = "Asia/Bangkok"
_DATES = [
    pd.Timestamp("2023-04-28", tz=_TZ),
    pd.Timestamp("2023-05-31", tz=_TZ),
    pd.Timestamp("2023-06-30", tz=_TZ),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _store(tmp_path: Path) -> ParquetStore:
    return ParquetStore(tmp_path / "processed")


# ---------------------------------------------------------------------------
# test 1 — z-score cross-sectional mean ≈ 0  (original test, kept)
# ---------------------------------------------------------------------------


def test_pipeline_z_scores_cross_sectionally(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    dates = [
        pd.Timestamp("2023-06-30", tz=_TZ),
        pd.Timestamp("2023-12-29", tz=_TZ),
    ]
    panel = FeaturePipeline(store=_store(tmp_path)).build(
        prices=sample_ohlcv_map, rebalance_dates=dates
    )
    for date in panel.index.get_level_values("date").unique():
        snapshot = panel.xs(date, level="date")
        assert abs(float(snapshot.mean().mean())) < 1e-6


# ---------------------------------------------------------------------------
# test 2 — z-score std ≈ 1 per feature per date
# ---------------------------------------------------------------------------


def test_z_score_std_approx_one(sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path) -> None:
    dates = [pd.Timestamp("2023-06-30", tz=_TZ), pd.Timestamp("2023-12-29", tz=_TZ)]
    panel = FeaturePipeline(store=_store(tmp_path)).build(
        prices=sample_ohlcv_map, rebalance_dates=dates
    )
    for date in panel.index.get_level_values("date").unique():
        snapshot = panel.xs(date, level="date")
        for col in snapshot.columns:
            assert abs(float(snapshot[col].std(ddof=0)) - 1.0) < 1e-4, (
                f"std of {col} on {date} is {snapshot[col].std(ddof=0):.6f}, expected ≈ 1"
            )


# ---------------------------------------------------------------------------
# test 3 — winsorization clips extreme outliers before z-scoring
# ---------------------------------------------------------------------------


def test_winsorization_clips_outliers(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    injected_map = {sym: df.copy() for sym, df in sample_ohlcv_map.items()}
    first_sym = next(iter(injected_map))
    injected_map[first_sym] = injected_map[first_sym].copy()
    injected_map[first_sym]["close"] = injected_map[first_sym]["close"] * 1e6

    dates = [pd.Timestamp("2023-06-30", tz=_TZ)]
    panel = FeaturePipeline(store=_store(tmp_path)).build(
        prices=injected_map, rebalance_dates=dates
    )
    snapshot = panel.xs(dates[0], level="date")
    max_abs_z = float(snapshot.abs().max().max())
    assert max_abs_z <= 4.0, f"max |z| = {max_abs_z:.2f} — winsorization may not have fired"


# ---------------------------------------------------------------------------
# test 4 — symbol with NaN feature is dropped from the panel
# ---------------------------------------------------------------------------


def test_symbol_with_nan_feature_dropped(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    rng = np.random.default_rng(0)
    short_dates = pd.date_range("2023-06-01", periods=10, freq="B", tz=_TZ)
    short_close = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 10))), index=short_dates)
    short_map = dict(sample_ohlcv_map)
    short_map["SHORT"] = pd.DataFrame({"close": short_close})

    dates = [pd.Timestamp("2023-06-30", tz=_TZ)]
    panel = FeaturePipeline(store=_store(tmp_path)).build(prices=short_map, rebalance_dates=dates)
    panel_symbols = set(panel.index.get_level_values("symbol").unique())
    assert "SHORT" not in panel_symbols


# ---------------------------------------------------------------------------
# test 5 — feature columns are float32
# ---------------------------------------------------------------------------


def test_feature_columns_float32(sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path) -> None:
    dates = [pd.Timestamp("2023-06-30", tz=_TZ)]
    panel = FeaturePipeline(store=_store(tmp_path)).build(
        prices=sample_ohlcv_map, rebalance_dates=dates
    )
    for col in panel.columns:
        assert panel[col].dtype == np.float32, f"column {col!r} dtype is {panel[col].dtype}"


# ---------------------------------------------------------------------------
# test 6 — sector_rel_strength in output when symbol_sectors provided
# ---------------------------------------------------------------------------


def test_sector_rel_strength_in_output(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    symbol_sectors = {sym: "AGRO" for sym in sample_ohlcv_map}
    dates = [pd.Timestamp("2023-06-30", tz=_TZ)]
    panel = FeaturePipeline(store=_store(tmp_path)).build(
        prices=sample_ohlcv_map,
        rebalance_dates=dates,
        symbol_sectors=symbol_sectors,
    )
    assert "sector_rel_strength" in panel.columns


# ---------------------------------------------------------------------------
# test 7 — build_forward_returns produces the expected column set
# ---------------------------------------------------------------------------


def test_build_forward_returns_columns(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    pipeline = FeaturePipeline(store=_store(tmp_path))
    panel = pipeline.build(prices=sample_ohlcv_map, rebalance_dates=_DATES)
    panel_fwd = pipeline.build_forward_returns(panel_df=panel, horizons=[1, 2])
    assert "fwd_ret_1m" in panel_fwd.columns
    assert "fwd_ret_2m" in panel_fwd.columns
    for col in panel.columns:
        assert col in panel_fwd.columns


# ---------------------------------------------------------------------------
# test 8 — forward return equals log(future/present) at consecutive rebalance dates
# ---------------------------------------------------------------------------


def test_forward_return_correct_value(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    pipeline = FeaturePipeline(store=_store(tmp_path))
    panel = pipeline.build(prices=sample_ohlcv_map, rebalance_dates=_DATES)
    panel_fwd = pipeline.build_forward_returns(panel_df=panel, horizons=[1])

    symbols_date0 = set(panel.xs(_DATES[0], level="date").index)
    symbols_date1 = set(panel.xs(_DATES[1], level="date").index)
    common = sorted(symbols_date0 & symbols_date1)
    assert common, "No symbol present on both first two rebalance dates"

    sym = common[0]
    close = sample_ohlcv_map[sym]["close"].sort_index()
    close_d0 = float(close.loc[close.index <= _DATES[0]].iloc[-1])
    close_d1 = float(close.loc[close.index <= _DATES[1]].iloc[-1])
    expected = float(np.log(close_d1 / close_d0))

    actual = float(panel_fwd.at[(_DATES[0], sym), "fwd_ret_1m"])
    assert abs(actual - expected) < 1e-4, f"expected {expected:.6f}, got {actual:.6f}"


# ---------------------------------------------------------------------------
# test 9 — forward return is NaN at the last rebalance date for horizon 1
# ---------------------------------------------------------------------------


def test_forward_return_nan_at_last_date(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    pipeline = FeaturePipeline(store=_store(tmp_path))
    panel = pipeline.build(prices=sample_ohlcv_map, rebalance_dates=_DATES)
    panel_fwd = pipeline.build_forward_returns(panel_df=panel, horizons=[1])

    last_date = _DATES[-1]
    panel_dates = set(panel.index.get_level_values("date").unique())
    assert last_date in panel_dates, "Last rebalance date must be in panel for this test"
    snapshot = panel_fwd.xs(last_date, level="date")
    assert snapshot["fwd_ret_1m"].isna().all()


# ---------------------------------------------------------------------------
# test 10 — empty panel when no prices provided
# ---------------------------------------------------------------------------


def test_empty_panel_on_empty_prices(tmp_path: Path) -> None:
    panel = FeaturePipeline(store=_store(tmp_path)).build(
        prices={}, rebalance_dates=[pd.Timestamp("2023-06-30", tz=_TZ)]
    )
    assert isinstance(panel.index, pd.MultiIndex)
    assert panel.index.names == ["date", "symbol"]
    assert len(panel) == 0


# ---------------------------------------------------------------------------
# test 11 — forward-return horizon drift prevention
#
# The panel has dates [A, C] (middle date B is removed).
# With the original 3-date calendar [A, B, C]:
#   horizon-1 at A → B   (log(close_B / close_A))
# With a buggy surviving-panel calendar [A, C]:
#   horizon-1 at A → C   (log(close_C / close_A))
# These differ, so the test detects if drift prevention is absent.
# ---------------------------------------------------------------------------


def test_forward_return_no_horizon_drift(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    pipeline = FeaturePipeline(store=_store(tmp_path))
    panel = pipeline.build(prices=sample_ohlcv_map, rebalance_dates=_DATES)

    panel_dates = set(panel.index.get_level_values("date").unique())
    assert _DATES[0] in panel_dates, "DATES[0] must be in panel"
    assert _DATES[1] in panel_dates, "DATES[1] must be in panel — all symbols need history"

    # Drop the MIDDLE date (DATES[1]) from the panel, simulating all symbols being NaN there.
    surviving_panel = panel.loc[panel.index.get_level_values("date").isin([_DATES[0], _DATES[2]])]

    # Pass the original 3-date calendar explicitly so build_forward_returns
    # uses the calendar-anchored shift (A→B), not the surviving-panel shift (A→C).
    panel_fwd = pipeline.build_forward_returns(
        panel_df=surviving_panel,
        horizons=[1],
        rebalance_dates=_DATES,
    )

    # Pick a symbol present on DATES[0].
    sym = sorted(surviving_panel.xs(_DATES[0], level="date").index)[0]
    close = sample_ohlcv_map[sym]["close"].sort_index()

    c_a = float(close.loc[close.index <= _DATES[0]].iloc[-1])
    c_b = float(close.loc[close.index <= _DATES[1]].iloc[-1])
    c_c = float(close.loc[close.index <= _DATES[2]].iloc[-1])

    correct = float(np.log(c_b / c_a))  # calendar-anchored: A → B
    drifted = float(np.log(c_c / c_a))  # panel-anchored (wrong): A → C

    actual = float(panel_fwd.at[(_DATES[0], sym), "fwd_ret_1m"])

    assert abs(actual - correct) < 1e-4, f"expected {correct:.6f} (calendar A→B), got {actual:.6f}"
    assert abs(actual - drifted) > 1e-4, (
        f"Forward return matches the drifted value {drifted:.6f} — drift prevention "
        "may not be working"
    )


# ---------------------------------------------------------------------------
# test 12 — horizon validation: empty list raises ValueError
# ---------------------------------------------------------------------------


def test_build_forward_returns_empty_horizons_raises(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    pipeline = FeaturePipeline(store=_store(tmp_path))
    panel = pipeline.build(prices=sample_ohlcv_map, rebalance_dates=_DATES)
    with pytest.raises(ValueError, match="horizons must not be empty"):
        pipeline.build_forward_returns(panel_df=panel, horizons=[])


# ---------------------------------------------------------------------------
# test 13 — horizon validation: non-positive value raises ValueError
# ---------------------------------------------------------------------------


def test_build_forward_returns_nonpositive_horizon_raises(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    pipeline = FeaturePipeline(store=_store(tmp_path))
    panel = pipeline.build(prices=sample_ohlcv_map, rebalance_dates=_DATES)
    with pytest.raises(ValueError, match="positive integers"):
        pipeline.build_forward_returns(panel_df=panel, horizons=[0])


# ---------------------------------------------------------------------------
# test 14 — horizon validation: duplicate values raise ValueError
# ---------------------------------------------------------------------------


def test_build_forward_returns_duplicate_horizons_raises(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    pipeline = FeaturePipeline(store=_store(tmp_path))
    panel = pipeline.build(prices=sample_ohlcv_map, rebalance_dates=_DATES)
    with pytest.raises(ValueError, match="duplicates"):
        pipeline.build_forward_returns(panel_df=panel, horizons=[1, 1])


# ---------------------------------------------------------------------------
# test 15 — build_forward_returns on empty panel adds fwd columns (all NaN)
#           Uses a FRESH pipeline instance with no cached state to prove the
#           empty-panel fast path does not require cached calendar or prices.
# ---------------------------------------------------------------------------


def test_build_forward_returns_empty_panel_adds_columns(tmp_path: Path) -> None:
    empty_index = pd.MultiIndex.from_arrays([[], []], names=["date", "symbol"])
    empty_panel = pd.DataFrame(index=empty_index)

    fresh_pipeline = FeaturePipeline(store=_store(tmp_path))
    result = fresh_pipeline.build_forward_returns(panel_df=empty_panel, horizons=[1])

    assert "fwd_ret_1m" in result.columns
    assert len(result) == 0
    assert result["fwd_ret_1m"].dtype == np.float32


# ---------------------------------------------------------------------------
# test 16 — build_forward_returns raises when panel date not in calendar
# ---------------------------------------------------------------------------


def test_build_forward_returns_missing_date_raises(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    pipeline = FeaturePipeline(store=_store(tmp_path))
    panel = pipeline.build(prices=sample_ohlcv_map, rebalance_dates=_DATES)

    panel_dates = set(panel.index.get_level_values("date").unique())
    assert _DATES[1] in panel_dates, (
        "DATES[1] must be in panel for this test to exercise the validation path"
    )

    # Pass only DATES[0] as the calendar — DATES[1] and DATES[2] are missing.
    with pytest.raises(ValueError, match="not present in the rebalance calendar"):
        pipeline.build_forward_returns(
            panel_df=panel,
            horizons=[1],
            rebalance_dates=[_DATES[0]],
        )


# ---------------------------------------------------------------------------
# test 17 — build_forward_returns raises when panel symbol not in prices
# ---------------------------------------------------------------------------


def test_build_forward_returns_missing_symbol_raises(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    pipeline = FeaturePipeline(store=_store(tmp_path))
    panel = pipeline.build(prices=sample_ohlcv_map, rebalance_dates=_DATES)

    panel_symbols = sorted(panel.index.get_level_values("symbol").unique())
    assert len(panel_symbols) >= 2, "Need at least 2 symbols for this test"

    excluded = panel_symbols[0]
    reduced_prices = {s: sample_ohlcv_map[s] for s in sample_ohlcv_map if s != excluded}

    with pytest.raises(ValueError, match="not present in prices"):
        pipeline.build_forward_returns(
            panel_df=panel,
            horizons=[1],
            prices=reduced_prices,
            rebalance_dates=_DATES,
        )


# ---------------------------------------------------------------------------
# test 18 — _validate_prices raises on missing 'close' column
# ---------------------------------------------------------------------------


def test_validate_prices_missing_close_raises(tmp_path: Path) -> None:
    bad_prices = {
        "SYM": pd.DataFrame(
            {"open": [1.0, 2.0]},
            index=pd.date_range("2023-01-01", periods=2, tz=_TZ),
        )
    }
    with pytest.raises(ValueError, match="missing the required 'close' column"):
        FeaturePipeline(store=_store(tmp_path)).build(
            prices=bad_prices,
            rebalance_dates=[pd.Timestamp("2023-01-31", tz=_TZ)],
        )


# ---------------------------------------------------------------------------
# test 19 — _validate_rebalance_dates raises on duplicate / unsorted dates
# ---------------------------------------------------------------------------


def test_validate_rebalance_dates_duplicates_raises(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="strictly monotonically increasing"):
        FeaturePipeline(store=_store(tmp_path)).build(
            prices=sample_ohlcv_map, rebalance_dates=[_DATES[0], _DATES[0]]
        )


def test_validate_rebalance_dates_unsorted_raises(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="strictly monotonically increasing"):
        FeaturePipeline(store=_store(tmp_path)).build(
            prices=sample_ohlcv_map, rebalance_dates=[_DATES[1], _DATES[0]]
        )


# ---------------------------------------------------------------------------
# Phase 3.8 — build_volume_matrix() pipes volumes from build() to the backtest
# ---------------------------------------------------------------------------


def test_build_volume_matrix_returns_wide_frame(
    sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    """After build(), volume cache is populated and build_volume_matrix() \
returns a wide DataFrame."""
    dates = [pd.Timestamp("2023-06-30", tz=_TZ), pd.Timestamp("2023-12-29", tz=_TZ)]
    pipeline = FeaturePipeline(store=_store(tmp_path))
    pipeline.build(prices=sample_ohlcv_map, rebalance_dates=dates)

    matrix = pipeline.build_volume_matrix()
    assert not matrix.empty
    # Index symbol excluded by default — only stock symbols in columns.
    assert "SET:SET" not in matrix.columns
    # Every stock symbol from the fixture appears as a column.
    expected_stock_syms = {s for s in sample_ohlcv_map if s != "SET:SET"}
    assert expected_stock_syms.issubset(set(matrix.columns))
    # Values are non-negative floats (synthetic fixture uses 2_000_000.0).
    assert (matrix.fillna(0) >= 0).all().all()


def test_build_volume_matrix_empty_before_build(tmp_path: Path) -> None:
    """Calling build_volume_matrix() before build() emits warning and returns empty frame."""
    pipeline = FeaturePipeline(store=_store(tmp_path))
    matrix = pipeline.build_volume_matrix()
    assert matrix.empty
