"""Tests for the OHLCV loader."""

from types import TracebackType

import pandas as pd
import pytest

from csm.config.settings import Settings
from csm.data.exceptions import DataAccessError
from csm.data.loader import OHLCVLoader

pytestmark = pytest.mark.asyncio


class _FakeBar:
    def __init__(self, timestamp: str, close: float) -> None:
        self.timestamp = timestamp
        self.open = close - 1.0
        self.high = close + 1.0
        self.low = close - 2.0
        self.close = close
        self.volume = 1_000.0


class _FakeOHLCV:
    async def __aenter__(self) -> "_FakeOHLCV":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def get_historical_ohlcv(
        self,
        symbol: str,
        interval: str,
        bars_count: int,
    ) -> list[_FakeBar]:
        return [
            _FakeBar("2024-01-01T00:00:00Z", 10.0),
            _FakeBar("2024-01-02T00:00:00Z", 11.0),
        ]


async def test_fetch_returns_correct_dataframe_schema(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
) -> None:
    monkeypatch.setattr("csm.data.loader.OHLCV", _FakeOHLCV)
    loader: OHLCVLoader = OHLCVLoader(settings_override)
    frame: pd.DataFrame = await loader.fetch(symbol="SET:AOT", interval="1D", bars=2)
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert str(frame.index.tz) == "Asia/Bangkok"


async def test_fetch_batch_returns_dict_keyed_by_symbol(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
) -> None:
    monkeypatch.setattr("csm.data.loader.OHLCV", _FakeOHLCV)
    loader: OHLCVLoader = OHLCVLoader(settings_override)
    payload: dict[str, pd.DataFrame] = await loader.fetch_batch(["SET:AOT", "SET:CPALL"], "1D", 2)
    assert sorted(payload.keys()) == ["SET:AOT", "SET:CPALL"]


async def test_fetch_raises_data_access_error_when_public_mode(public_settings: Settings) -> None:
    loader: OHLCVLoader = OHLCVLoader(public_settings)
    with pytest.raises(DataAccessError):
        await loader.fetch(symbol="SET:AOT", interval="1D", bars=2)


async def test_fetch_batch_raises_data_access_error_when_public_mode(public_settings: Settings) -> None:
    loader: OHLCVLoader = OHLCVLoader(public_settings)
    with pytest.raises(DataAccessError):
        await loader.fetch_batch(symbols=["SET:AOT"], interval="1D", bars=2)