"""Unit tests for ParquetStore."""

from pathlib import Path

import pandas as pd
import pytest

from csm.data.exceptions import StoreError
from csm.data.store import ParquetStore


def _ohlcv_frame(tz: str = "UTC") -> pd.DataFrame:
    index: pd.DatetimeIndex = pd.DatetimeIndex(
        ["2024-01-02", "2024-01-03", "2024-01-04"],
        name="datetime",
        tz=tz,
    )
    return pd.DataFrame(
        {
            "open": pd.array([10.0, 11.0, 12.0], dtype="float64"),
            "close": pd.array([10.5, 11.5, 12.5], dtype="float64"),
            "volume": pd.array([1_000_000, 2_000_000, 3_000_000], dtype="int64"),
            "label": pd.array(["a", "b", "c"], dtype="object"),
        },
        index=index,
    )


def test_round_trip_preserves_datetime_index_utc(tmp_path: Path) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "raw")
    df: pd.DataFrame = _ohlcv_frame(tz="UTC")
    store.save("SET:AOT", df)
    loaded: pd.DataFrame = store.load("SET:AOT")
    assert isinstance(loaded.index, pd.DatetimeIndex)
    assert str(loaded.index.tz) == "UTC"
    assert loaded.index.name == "datetime"


def test_round_trip_preserves_column_dtypes(tmp_path: Path) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "raw")
    df: pd.DataFrame = _ohlcv_frame()
    store.save("SET:AOT", df)
    loaded: pd.DataFrame = store.load("SET:AOT")
    assert str(loaded["open"].dtype) == "float64"
    assert str(loaded["volume"].dtype) == "int64"
    # pyarrow encodes object string columns as the `string` extension dtype on load
    assert pd.api.types.is_string_dtype(loaded["label"])


def test_save_returns_none(tmp_path: Path) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "raw")
    # Verify the return type annotation is honoured: save() must return None
    assert store.save("SET:AOT", _ohlcv_frame()) is None  # type: ignore[func-returns-value]


def test_overwrite_does_not_raise(tmp_path: Path) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "raw")
    df_v1: pd.DataFrame = _ohlcv_frame()
    store.save("SET:AOT", df_v1)
    df_v2: pd.DataFrame = _ohlcv_frame()
    df_v2["open"] = 99.0
    store.save("SET:AOT", df_v2)
    loaded: pd.DataFrame = store.load("SET:AOT")
    assert float(loaded["open"].iloc[0]) == pytest.approx(99.0)


def test_load_raises_key_error_for_missing_key(tmp_path: Path) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "raw")
    with pytest.raises(KeyError):
        store.load("SET:MISSING")


def test_exists_false_before_save_true_after(tmp_path: Path) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "raw")
    assert store.exists("SET:AOT") is False
    store.save("SET:AOT", _ohlcv_frame())
    assert store.exists("SET:AOT") is True


def test_list_keys_returns_sorted_canonical_keys(tmp_path: Path) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "raw")
    store.save("SET:AOT", _ohlcv_frame())
    store.save("SET:ADVANC", _ohlcv_frame())
    assert store.list_keys() == ["SET:ADVANC", "SET:AOT"]


def test_delete_removes_file_second_delete_raises_key_error(tmp_path: Path) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "raw")
    store.save("SET:AOT", _ohlcv_frame())
    store.delete("SET:AOT")
    assert store.exists("SET:AOT") is False
    with pytest.raises(KeyError):
        store.delete("SET:AOT")
