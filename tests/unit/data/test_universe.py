"""Unit tests for UniverseBuilder."""

from pathlib import Path

import pandas as pd

from csm.config.constants import UNKNOWN_SECTOR
from csm.config.settings import Settings
from csm.data.store import ParquetStore
from csm.data.universe import UniverseBuilder


def _make_ohlcv(
    n: int = 500,
    close: float = 100.0,
    volume: float = 2_000_000.0,
) -> pd.DataFrame:
    """Return a synthetic OHLCV DataFrame with n business-day rows."""
    dates = pd.date_range("2022-01-03", periods=n, freq="B", tz="Asia/Bangkok")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def _builder(tmp_path: Path) -> tuple[ParquetStore, UniverseBuilder]:
    store = ParquetStore(tmp_path)
    return store, UniverseBuilder(store, Settings())


_ASOF = pd.Timestamp("2024-01-01", tz="Asia/Bangkok")


def test_price_filter_rejects_low_close(tmp_path: Path) -> None:
    store, builder = _builder(tmp_path)
    store.save("SET:LOW", _make_ohlcv(close=0.5))  # below MIN_PRICE_THB = 1.0
    assert builder.filter("SET:LOW", _ASOF) is False


def test_volume_filter_rejects_low_volume(tmp_path: Path) -> None:
    store, builder = _builder(tmp_path)
    store.save("SET:ILLIQ", _make_ohlcv(volume=100.0))  # below MIN_AVG_DAILY_VOLUME
    assert builder.filter("SET:ILLIQ", _ASOF) is False


def test_coverage_filter_rejects_sparse_data(tmp_path: Path) -> None:
    store, builder = _builder(tmp_path)
    df = _make_ohlcv()
    # Set 22% of bars to NaN — exceeds the 20% missing tolerance
    nan_count = int(len(df) * 0.22)
    df.iloc[:nan_count, df.columns.get_loc("close")] = float("nan")
    store.save("SET:SPARSE", df)
    assert builder.filter("SET:SPARSE", _ASOF) is False


def test_filter_returns_false_for_missing_symbol(tmp_path: Path) -> None:
    _, builder = _builder(tmp_path)
    # "SET:GHOST" has never been saved to the store
    assert builder.filter("SET:GHOST", _ASOF) is False


def test_build_snapshot_no_lookahead(tmp_path: Path) -> None:
    store, builder = _builder(tmp_path)
    dates = pd.date_range("2022-01-03", periods=500, freq="B", tz="Asia/Bangkok")
    cutoff = dates[249]  # midpoint

    # First 250 bars: close = 0.5 (fails price filter)
    # Last  250 bars: close = 100.0 (passes price filter)
    df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 0.49,
            "close": [0.5] * 250 + [100.0] * 250,
            "volume": 2_000_000.0,
        },
        index=dates,
    )
    store.save("SET:GROW", df)

    # At cutoff, latest close is 0.5 — should NOT pass
    assert "SET:GROW" not in builder.build_snapshot(cutoff, ["SET:GROW"])
    # After all data is available, latest close is 100.0 — should pass
    assert "SET:GROW" in builder.build_snapshot(dates[-1], ["SET:GROW"])


def test_build_all_snapshots_one_per_date(tmp_path: Path) -> None:
    raw_store = ParquetStore(tmp_path / "raw")
    universe_store = ParquetStore(tmp_path / "universe")
    raw_store.save("SET:GOOD", _make_ohlcv())

    builder = UniverseBuilder(raw_store, Settings())
    rebalance_dates = pd.date_range("2023-06-30", periods=3, freq="BME", tz="Asia/Bangkok")
    builder.build_all_snapshots(["SET:GOOD"], rebalance_dates, snapshot_store=universe_store)

    for date in rebalance_dates:
        key = f"universe/{date.strftime('%Y-%m-%d')}"
        assert universe_store.exists(key), f"Missing snapshot for {key}"
        snapshot = universe_store.load(key)
        assert "symbol" in snapshot.columns
        assert "asof" in snapshot.columns

    universe_keys = universe_store.list_keys()
    assert len(universe_keys) == len(rebalance_dates)


def test_snapshots_carry_sector_when_mapping_supplied(tmp_path: Path) -> None:
    """``sector`` is what unlocks ``sector_rel_strength`` in the feature pipeline.

    The pipeline needs a ``symbol_sectors`` mapping; the daily refresh can only
    build one from the universe snapshot it already loads; and the snapshot
    carried no sector at all — so the factor was never computed.
    """
    raw_store = ParquetStore(tmp_path / "raw")
    universe_store = ParquetStore(tmp_path / "universe")
    raw_store.save("SET:GOOD", _make_ohlcv())

    builder = UniverseBuilder(raw_store, Settings())
    dates = pd.date_range("2023-06-30", periods=2, freq="BME", tz="Asia/Bangkok")
    builder.build_all_snapshots(
        ["SET:GOOD"],
        dates,
        snapshot_store=universe_store,
        symbol_sectors={"SET:GOOD": "ETRON"},
    )

    snapshot = universe_store.load(f"universe/{dates[0].strftime('%Y-%m-%d')}")
    assert list(snapshot.columns) == ["symbol", "asof", "sector"]
    assert snapshot.loc[snapshot["symbol"] == "SET:GOOD", "sector"].iloc[0] == "ETRON"


def test_unclassified_symbol_is_labelled_not_dropped(tmp_path: Path) -> None:
    """A missing sector must never shrink the tradeable universe."""
    raw_store = ParquetStore(tmp_path / "raw")
    universe_store = ParquetStore(tmp_path / "universe")
    raw_store.save("SET:GOOD", _make_ohlcv())

    builder = UniverseBuilder(raw_store, Settings())
    dates = pd.date_range("2023-06-30", periods=1, freq="BME", tz="Asia/Bangkok")
    builder.build_all_snapshots(
        ["SET:GOOD"], dates, snapshot_store=universe_store, symbol_sectors={}
    )

    snapshot = universe_store.load(f"universe/{dates[0].strftime('%Y-%m-%d')}")
    assert "SET:GOOD" in set(snapshot["symbol"]), "an unclassified symbol must survive"
    assert snapshot["sector"].iloc[0] == UNKNOWN_SECTOR


def test_no_sector_column_when_mapping_omitted(tmp_path: Path) -> None:
    """Omitting the mapping leaves the schema exactly as it was.

    Keeps a refresh against an older snapshot working rather than erroring.
    """
    raw_store = ParquetStore(tmp_path / "raw")
    universe_store = ParquetStore(tmp_path / "universe")
    raw_store.save("SET:GOOD", _make_ohlcv())

    builder = UniverseBuilder(raw_store, Settings())
    dates = pd.date_range("2023-06-30", periods=1, freq="BME", tz="Asia/Bangkok")
    builder.build_all_snapshots(["SET:GOOD"], dates, snapshot_store=universe_store)

    snapshot = universe_store.load(f"universe/{dates[0].strftime('%Y-%m-%d')}")
    assert "sector" not in snapshot.columns
