"""Tests for CrossSectionalRanker — Phase 2.5."""

from collections.abc import Callable
from typing import TypeVar, cast

import pandas as pd
import pytest

from csm.research.ranking import CrossSectionalRanker

_TZ = "Asia/Bangkok"
_DATES = [
    pd.Timestamp("2024-01-31", tz=_TZ),
    pd.Timestamp("2024-02-29", tz=_TZ),
]

FixtureFunction = TypeVar("FixtureFunction", bound=Callable[..., object])
fixture = cast(Callable[[FixtureFunction], FixtureFunction], pytest.fixture)


def _make_panel(
    signal: list[float],
    n_symbols: int = 10,
    dates: list[pd.Timestamp] | None = None,
    extra_cols: dict[str, list[float]] | None = None,
) -> pd.DataFrame:
    """Build a synthetic MultiIndex panel for testing."""
    _dates = dates if dates is not None else _DATES
    symbols = [f"SYM{i:02d}" for i in range(n_symbols)]
    idx = pd.MultiIndex.from_product([_dates, symbols], names=["date", "symbol"])
    data: dict[str, list[float]] = {"mom_12_1": signal * len(_dates)}
    if extra_cols:
        for col, vals in extra_cols.items():
            data[col] = vals * len(_dates)
    return pd.DataFrame(data, index=idx, dtype="float64")


@fixture
def panel_df() -> pd.DataFrame:
    """10 symbols × 2 dates; mom_12_1 linearly spread (SYM00=10 highest, SYM09=1 lowest)."""
    signal = list(range(10, 0, -1))  # [10, 9, ..., 1]
    return _make_panel(signal)


# ---------------------------------------------------------------------------
# Test 1: percentile ranks are in (0, 1]
# ---------------------------------------------------------------------------


def test_rank_percentiles_in_range(panel_df: pd.DataFrame) -> None:
    result = CrossSectionalRanker().rank(panel_df, "mom_12_1")
    ranks = result["mom_12_1_rank"].dropna()
    assert (ranks > 0.0).all(), "ranks must be > 0 (rank(pct=True) never produces 0)"
    assert (ranks <= 1.0).all(), "ranks must be <= 1"


# ---------------------------------------------------------------------------
# Test 2: quintile counts balanced (~N/5) per date
# ---------------------------------------------------------------------------


def test_rank_quintile_counts_balanced(panel_df: pd.DataFrame) -> None:
    result = CrossSectionalRanker().rank(panel_df, "mom_12_1")
    for date in _DATES:
        snapshot = result.xs(date, level="date")
        counts = snapshot["mom_12_1_quintile"].value_counts()
        for q in [1, 2, 3, 4, 5]:
            assert counts.get(q, 0) == 2, f"expected 2 symbols in quintile {q} on {date}"


# ---------------------------------------------------------------------------
# Test 3: highest signal → quintile 5, lowest → quintile 1
# ---------------------------------------------------------------------------


def test_rank_quintile_ordering(panel_df: pd.DataFrame) -> None:
    result = CrossSectionalRanker().rank(panel_df, "mom_12_1")
    date = _DATES[0]
    snapshot = result.xs(date, level="date")
    highest = snapshot["mom_12_1"].idxmax()
    lowest = snapshot["mom_12_1"].idxmin()
    assert snapshot.loc[highest, "mom_12_1_quintile"] == 5
    assert snapshot.loc[lowest, "mom_12_1_quintile"] == 1


# ---------------------------------------------------------------------------
# Test 4: NaN symbol excluded from ranking on that date; other dates unaffected
# ---------------------------------------------------------------------------


def test_rank_drops_nan_symbols(panel_df: pd.DataFrame) -> None:
    panel_with_nan = panel_df.copy()
    date, sym = _DATES[0], "SYM00"
    panel_with_nan.loc[(date, sym), "mom_12_1"] = float("nan")
    result = CrossSectionalRanker().rank(panel_with_nan, "mom_12_1")

    assert pd.isna(result.loc[(date, sym), "mom_12_1_rank"])
    assert pd.isna(result.loc[(date, sym), "mom_12_1_quintile"])

    other_rank = result.loc[(_DATES[1], sym), "mom_12_1_rank"]
    assert not pd.isna(other_rank), "NaN on one date must not affect the other date"
    assert 0 < other_rank <= 1.0


# ---------------------------------------------------------------------------
# Test 5: rank_all() adds rank/quintile for all numeric feature columns
# ---------------------------------------------------------------------------


def test_rank_all_covers_all_features() -> None:
    signal = list(range(10, 0, -1))
    df = _make_panel(signal, extra_cols={"mom_6_1": list(range(1, 11))})
    result = CrossSectionalRanker().rank_all(df)
    for col in ["mom_12_1_rank", "mom_12_1_quintile", "mom_6_1_rank", "mom_6_1_quintile"]:
        assert col in result.columns, f"expected column {col!r} in rank_all() output"


# ---------------------------------------------------------------------------
# Test 6: rank_all() skips fwd_ret_* columns
# ---------------------------------------------------------------------------


def test_rank_all_skips_fwd_ret_columns() -> None:
    signal = list(range(10, 0, -1))
    df = _make_panel(signal, extra_cols={"fwd_ret_1m": list(range(1, 11))})
    result = CrossSectionalRanker().rank_all(df)
    assert "fwd_ret_1m_rank" not in result.columns
    assert "mom_12_1_rank" in result.columns


# ---------------------------------------------------------------------------
# Test 7: ValueError on missing signal_col
# ---------------------------------------------------------------------------


def test_rank_raises_on_missing_column(panel_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="not found in panel_df columns"):
        CrossSectionalRanker().rank(panel_df, "nonexistent")


# ---------------------------------------------------------------------------
# Test 8: ties share the correct average rank (method='average' verified)
# ---------------------------------------------------------------------------


def test_rank_ties_share_average_rank() -> None:
    # 6 symbols: S0..S2 tied at 10.0; S3=3.0, S4=2.0, S5=1.0
    # ascending rank: 1.0→1, 2.0→2, 3.0→3, {10.0,10.0,10.0}→avg(4,5,6)=5.0
    # pct rank for tied group = 5.0 / 6 ≈ 0.8333
    symbols = [f"S{i}" for i in range(6)]
    idx = pd.MultiIndex.from_product([[_DATES[0]], symbols], names=["date", "symbol"])
    df = pd.DataFrame({"mom_12_1": [10.0, 10.0, 10.0, 3.0, 2.0, 1.0]}, index=idx)
    result = CrossSectionalRanker().rank(df, "mom_12_1")
    snapshot = result.xs(_DATES[0], level="date")

    tied_ranks = snapshot.loc[["S0", "S1", "S2"], "mom_12_1_rank"]
    assert tied_ranks.nunique() == 1, "tied symbols must share equal rank"
    expected_rank = 5.0 / 6.0
    assert abs(float(tied_ranks.iloc[0]) - expected_rank) < 1e-9


# ---------------------------------------------------------------------------
# Test 9: small cross-section (3 symbols) uses fallback labels; ordering preserved
# ---------------------------------------------------------------------------


def test_rank_small_cross_section_fallback_labels() -> None:
    # 3 symbols — qcut with 5 labels fails; fallback produces sparse labels
    symbols = ["A", "B", "C"]
    idx = pd.MultiIndex.from_product([[_DATES[0]], symbols], names=["date", "symbol"])
    df = pd.DataFrame({"mom_12_1": [3.0, 2.0, 1.0]}, index=idx)
    result = CrossSectionalRanker().rank(df, "mom_12_1")
    snapshot = result.xs(_DATES[0], level="date")

    # Ranks must be valid
    assert snapshot["mom_12_1_rank"].notna().all()
    # Highest signal gets highest label, lowest gets lowest label
    assert snapshot.loc["A", "mom_12_1_quintile"] > snapshot.loc["C", "mom_12_1_quintile"]
    assert int(snapshot.loc["A", "mom_12_1_quintile"]) == 5
    assert int(snapshot.loc["C", "mom_12_1_quintile"]) == 1


# ---------------------------------------------------------------------------
# Test 10: input validation — TypeError on non-DataFrame
# ---------------------------------------------------------------------------


def test_rank_raises_type_error_on_non_dataframe() -> None:
    with pytest.raises(TypeError, match="pd.DataFrame"):
        CrossSectionalRanker().rank({"not": "a dataframe"}, "mom_12_1")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 11: input validation — ValueError on flat index
# ---------------------------------------------------------------------------


def test_rank_raises_on_flat_index() -> None:
    df = pd.DataFrame({"mom_12_1": [1.0, 2.0]})
    with pytest.raises(ValueError, match="pd.MultiIndex"):
        CrossSectionalRanker().rank(df, "mom_12_1")


# ---------------------------------------------------------------------------
# Test 12: input validation — ValueError on wrong MultiIndex names
# ---------------------------------------------------------------------------


def test_rank_raises_on_wrong_index_names() -> None:
    idx = pd.MultiIndex.from_tuples([("2024-01", "A"), ("2024-01", "B")], names=["ts", "ticker"])
    df = pd.DataFrame({"mom_12_1": [1.0, 2.0]}, index=idx)
    with pytest.raises(ValueError, match="date.*symbol"):
        CrossSectionalRanker().rank(df, "mom_12_1")


# ---------------------------------------------------------------------------
# Test 13: copy semantics — input panel unchanged after rank()
# ---------------------------------------------------------------------------


def test_rank_does_not_mutate_input(panel_df: pd.DataFrame) -> None:
    original_cols = list(panel_df.columns)
    CrossSectionalRanker().rank(panel_df, "mom_12_1")
    assert list(panel_df.columns) == original_cols, "rank() must not mutate the input DataFrame"


# ---------------------------------------------------------------------------
# Test 14: rank_all() skips existing _rank / _quintile columns
# ---------------------------------------------------------------------------


def test_rank_all_skips_already_ranked_columns() -> None:
    signal = list(range(10, 0, -1))
    df = _make_panel(signal)
    # Pre-rank once to add _rank / _quintile columns
    pre_ranked = CrossSectionalRanker().rank_all(df)
    # rank_all on the pre-ranked frame should not produce double-suffixed columns
    result = CrossSectionalRanker().rank_all(pre_ranked)
    assert "mom_12_1_rank_rank" not in result.columns
    assert "mom_12_1_quintile_quintile" not in result.columns


# ---------------------------------------------------------------------------
# Test 15: rank_all() skips non-numeric columns
# ---------------------------------------------------------------------------


def test_rank_all_skips_non_numeric_columns() -> None:
    symbols = [f"SYM{i:02d}" for i in range(10)]
    idx = pd.MultiIndex.from_product([[_DATES[0]], symbols], names=["date", "symbol"])
    df = pd.DataFrame(
        {
            "mom_12_1": list(range(10, 0, -1)),
            "sector": ["AGRO"] * 10,
        },
        index=idx,
    )
    result = CrossSectionalRanker().rank_all(df)
    assert "sector_rank" not in result.columns
    assert "mom_12_1_rank" in result.columns
