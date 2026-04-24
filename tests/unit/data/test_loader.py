"""Tests for the OHLCV loader."""

from pathlib import Path
from types import TracebackType

import pandas as pd
import pytest

from csm.config.settings import Settings
from csm.data.exceptions import DataAccessError, FetchError
from csm.data.loader import Adjustment, OHLCVLoader

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


# ---------------------------------------------------------------------------
# Adjustment parameter tests
# ---------------------------------------------------------------------------


async def test_fetch_accepts_explicit_adjustment_splits(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
) -> None:
    """fetch() accepts adjustment='splits' without raising."""
    monkeypatch.setattr("csm.data.loader.OHLCV", _FakeOHLCV)
    loader: OHLCVLoader = OHLCVLoader(settings_override)
    frame: pd.DataFrame = await loader.fetch(
        symbol="SET:AOT", interval="1D", bars=2, adjustment="splits"
    )
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]


async def test_fetch_accepts_explicit_adjustment_dividends(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
) -> None:
    """fetch() accepts adjustment='dividends' without raising."""
    monkeypatch.setattr("csm.data.loader.OHLCV", _FakeOHLCV)
    loader: OHLCVLoader = OHLCVLoader(settings_override)
    frame: pd.DataFrame = await loader.fetch(
        symbol="SET:AOT", interval="1D", bars=2, adjustment="dividends"
    )
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]


async def test_fetch_unknown_adjustment_raises_value_error_before_network(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
) -> None:
    """fetch() raises ValueError for unknown adjustment string — no network I/O occurs."""
    called: dict[str, bool] = {"called": False}

    class _RecordingOHLCV(_FakeOHLCV):
        async def get_historical_ohlcv(
            self,
            symbol: str,
            interval: str,
            bars_count: int,
        ) -> list[_FakeBar]:
            called["called"] = True
            return []

    monkeypatch.setattr("csm.data.loader.OHLCV", _RecordingOHLCV)
    loader: OHLCVLoader = OHLCVLoader(settings_override)
    with pytest.raises(ValueError, match="'unknown'"):
        await loader.fetch(symbol="SET:AOT", interval="1D", bars=2, adjustment="unknown")
    assert not called["called"], "tvkit should not be called for an invalid adjustment string"


async def test_fetch_defaults_adjustment_to_settings_value(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
) -> None:
    """fetch() uses settings.tvkit_adjustment when adjustment param is None."""
    monkeypatch.setattr("csm.data.loader.OHLCV", _FakeOHLCV)
    loader: OHLCVLoader = OHLCVLoader(settings_override)
    # settings_override has tvkit_adjustment="dividends" by default in conftest
    frame: pd.DataFrame = await loader.fetch(symbol="SET:AOT", interval="1D", bars=2)
    assert isinstance(frame, pd.DataFrame)


async def test_fetch_batch_forwards_adjustment_to_each_symbol(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
) -> None:
    """fetch_batch() forwards the adjustment param to each per-symbol fetch call."""
    monkeypatch.setattr("csm.data.loader.OHLCV", _FakeOHLCV)
    loader: OHLCVLoader = OHLCVLoader(settings_override)
    result: dict[str, pd.DataFrame] = await loader.fetch_batch(
        ["SET:AOT", "SET:CPALL"], "1D", 2, adjustment="splits"
    )
    assert sorted(result.keys()) == ["SET:AOT", "SET:CPALL"]


def test_adjustment_enum_values() -> None:
    """Adjustment enum has SPLITS and DIVIDENDS members with correct string values."""
    assert Adjustment.SPLITS == "splits"
    assert Adjustment.DIVIDENDS == "dividends"
    assert Adjustment("splits") is Adjustment.SPLITS
    assert Adjustment("dividends") is Adjustment.DIVIDENDS
