"""Tests for the OHLCV loader."""

from pathlib import Path
from types import TracebackType

import pandas as pd
import pytest

from csm.config.settings import Settings
from csm.data.exceptions import DataAccessError, FetchError
from csm.data.loader import OHLCVLoader

pytestmark = pytest.mark.asyncio


@pytest.fixture
def monkeypatch_settings_with_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Settings:
    """Settings with tvkit_retry_attempts=2 for retry-logic tests."""
    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CSM_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("CSM_PUBLIC_MODE", "false")
    monkeypatch.setenv("CSM_TVKIT_RETRY_ATTEMPTS", "2")
    return Settings()


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
    assert frame.index.name == "datetime"
    assert frame.index.is_monotonic_increasing


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


async def test_fetch_batch_raises_data_access_error_when_public_mode(
    public_settings: Settings,
) -> None:
    loader: OHLCVLoader = OHLCVLoader(public_settings)
    with pytest.raises(DataAccessError):
        await loader.fetch_batch(symbols=["SET:AOT"], interval="1D", bars=2)


async def test_fetch_batch_continues_after_symbol_failure(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
) -> None:
    """Failed symbol is absent from result; other symbols succeed."""

    call_count: dict[str, int] = {"count": 0}

    class _FailOnFirstCallOHLCV:
        async def __aenter__(self) -> "_FailOnFirstCallOHLCV":
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
            call_count["count"] += 1
            if symbol == "SET:FAIL":
                raise ValueError("symbol not found")
            return [_FakeBar("2024-01-01T00:00:00Z", 10.0)]

    monkeypatch.setattr("csm.data.loader.OHLCV", _FailOnFirstCallOHLCV)
    loader: OHLCVLoader = OHLCVLoader(settings_override)
    result: dict[str, pd.DataFrame] = await loader.fetch_batch(
        symbols=["SET:FAIL", "SET:AOT"],
        interval="1D",
        bars=1,
    )
    assert "SET:FAIL" not in result
    assert "SET:AOT" in result
    assert isinstance(result["SET:AOT"], pd.DataFrame)


async def test_fetch_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_settings_with_retries: Settings,
) -> None:
    """fetch() retries on OSError and returns DataFrame on the final successful attempt."""

    call_count: dict[str, int] = {"count": 0}

    class _FailTwiceOHLCV:
        async def __aenter__(self) -> "_FailTwiceOHLCV":
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
            call_count["count"] += 1
            if call_count["count"] <= 2:
                raise OSError("connection reset")
            return [_FakeBar("2024-01-01T00:00:00Z", 10.0)]

    monkeypatch.setattr("csm.data.loader.OHLCV", _FailTwiceOHLCV)
    loader: OHLCVLoader = OHLCVLoader(monkeypatch_settings_with_retries)
    frame: pd.DataFrame = await loader.fetch(symbol="SET:AOT", interval="1D", bars=1)
    assert call_count["count"] == 3
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 1


async def test_fetch_raises_fetch_error_when_all_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_settings_with_retries: Settings,
) -> None:
    """fetch() raises FetchError after exhausting all retry attempts."""

    class _AlwaysFailOHLCV:
        async def __aenter__(self) -> "_AlwaysFailOHLCV":
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
            raise OSError("connection reset")

    monkeypatch.setattr("csm.data.loader.OHLCV", _AlwaysFailOHLCV)
    loader: OHLCVLoader = OHLCVLoader(monkeypatch_settings_with_retries)
    with pytest.raises(FetchError, match="all retries exhausted"):
        await loader.fetch(symbol="SET:AOT", interval="1D", bars=1)
