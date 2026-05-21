"""Unit tests for :class:`csm.data.benchmark.BenchmarkLoader`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from csm.config.settings import Settings
from csm.data.benchmark import BenchmarkLoader
from csm.data.exceptions import BenchmarkUnavailableError
from csm.data.store import ParquetStore


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    return ParquetStore(base_dir=tmp_path)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CSM_BENCHMARK_SYMBOL", "BENCH")
    return Settings()


def _write_prices(store: ParquetStore, values: dict[str, list[float]]) -> None:
    idx: pd.DatetimeIndex = pd.date_range(
        start="2026-01-01", periods=len(next(iter(values.values()))), freq="D", tz="UTC"
    )
    frame: pd.DataFrame = pd.DataFrame(values, index=idx)
    store.save("prices_latest", frame)


async def test_load_normalises_to_initial_capital(store: ParquetStore, settings: Settings) -> None:
    _write_prices(store, {"BENCH": [100.0, 110.0, 120.0]})
    loader: BenchmarkLoader = BenchmarkLoader(settings=settings, store=store)
    series: pd.Series = await loader.load(initial_capital=Decimal("200000"))
    assert series.iloc[0] == pytest.approx(200_000.0)
    assert series.iloc[1] == pytest.approx(220_000.0)
    assert series.iloc[2] == pytest.approx(240_000.0)
    assert series.name == "benchmark_equity"
    assert series.index.tz is not None


async def test_load_filters_by_start_and_end(store: ParquetStore, settings: Settings) -> None:
    _write_prices(store, {"BENCH": [100.0, 110.0, 120.0, 130.0]})
    loader: BenchmarkLoader = BenchmarkLoader(settings=settings, store=store)
    start: datetime = datetime(2026, 1, 2, tzinfo=UTC)
    end: datetime = datetime(2026, 1, 3, tzinfo=UTC)
    series: pd.Series = await loader.load(initial_capital=Decimal("100000"), start=start, end=end)
    assert len(series) == 2


async def test_load_raises_when_column_missing(store: ParquetStore, settings: Settings) -> None:
    _write_prices(store, {"OTHER": [100.0, 110.0]})
    loader: BenchmarkLoader = BenchmarkLoader(settings=settings, store=store)
    with pytest.raises(BenchmarkUnavailableError):
        await loader.load(initial_capital=Decimal("100000"))


async def test_load_raises_when_panel_empty(store: ParquetStore, settings: Settings) -> None:
    empty: pd.DataFrame = pd.DataFrame({"BENCH": []}, index=pd.DatetimeIndex([], tz="UTC"))
    store.save("prices_latest", empty)
    loader: BenchmarkLoader = BenchmarkLoader(settings=settings, store=store)
    with pytest.raises(BenchmarkUnavailableError):
        await loader.load(initial_capital=Decimal("100000"))


async def test_load_raises_when_filtered_empty(store: ParquetStore, settings: Settings) -> None:
    _write_prices(store, {"BENCH": [100.0, 110.0]})
    loader: BenchmarkLoader = BenchmarkLoader(settings=settings, store=store)
    with pytest.raises(BenchmarkUnavailableError):
        await loader.load(
            initial_capital=Decimal("100000"),
            start=datetime(2027, 1, 1, tzinfo=UTC),
        )


async def test_load_raises_when_index_tz_naive(store: ParquetStore, settings: Settings) -> None:
    idx: pd.DatetimeIndex = pd.date_range("2026-01-01", periods=2, freq="D")  # naive
    frame: pd.DataFrame = pd.DataFrame({"BENCH": [100.0, 110.0]}, index=idx)
    store.save("prices_latest", frame)
    loader: BenchmarkLoader = BenchmarkLoader(settings=settings, store=store)
    with pytest.raises(BenchmarkUnavailableError):
        await loader.load(initial_capital=Decimal("100000"))


async def test_load_raises_when_first_value_non_positive(
    store: ParquetStore, settings: Settings
) -> None:
    _write_prices(store, {"BENCH": [0.0, 100.0]})
    loader: BenchmarkLoader = BenchmarkLoader(settings=settings, store=store)
    with pytest.raises(BenchmarkUnavailableError):
        await loader.load(initial_capital=Decimal("100000"))
