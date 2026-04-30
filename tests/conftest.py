"""Shared pytest fixtures for csm-set."""

from collections.abc import Callable, Generator
from pathlib import Path
from typing import TypeVar, cast

import numpy as np
import pandas as pd
import pytest

from csm.config.settings import Settings
from csm.data.store import ParquetStore

FixtureFunction = TypeVar("FixtureFunction", bound=Callable[..., object])
fixture = cast(Callable[[FixtureFunction], FixtureFunction], pytest.fixture)


@fixture
def sample_prices() -> pd.DataFrame:
    """100 symbols x 500 trading days of synthetic close prices, tz-aware Asia/Bangkok."""

    rng: np.random.Generator = np.random.default_rng(42)
    dates: pd.DatetimeIndex = pd.date_range("2022-01-03", periods=500, freq="B", tz="Asia/Bangkok")
    symbols: list[str] = [f"SET{index:03d}" for index in range(100)]
    returns: np.ndarray = rng.normal(loc=0.0005, scale=0.02, size=(len(dates), len(symbols)))
    prices: np.ndarray = 100.0 * np.exp(np.cumsum(returns, axis=0))
    return pd.DataFrame(prices, index=dates, columns=symbols)


@fixture
def sample_universe() -> list[str]:
    """List of 50 symbol names matching sample_prices columns."""

    return [f"SET{index:03d}" for index in range(50)]


@fixture
def settings_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Override data and result directories for private-mode tests."""

    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CSM_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("CSM_PUBLIC_MODE", "false")
    return Settings()


@fixture
def public_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with public_mode=True for boundary-enforcement tests."""

    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CSM_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("CSM_PUBLIC_MODE", "true")
    return Settings()


@fixture
def sample_ohlcv_map(sample_prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Map synthetic close prices into OHLCV DataFrames keyed by symbol."""

    ohlcv_map: dict[str, pd.DataFrame] = {}
    for symbol in sample_prices.columns:
        close_series: pd.Series = sample_prices[symbol]
        ohlcv_map[symbol] = pd.DataFrame(
            {
                "open": close_series.shift(1).fillna(close_series.iloc[0]),
                "high": close_series * 1.01,
                "low": close_series * 0.99,
                "close": close_series,
                "volume": pd.Series(2_000_000.0, index=close_series.index, dtype=float),
            },
            index=close_series.index,
        )
    return ohlcv_map


@fixture
def tmp_results(tmp_path: Path) -> Path:
    """Create temporary results payloads for public-mode API tests."""

    results_dir: Path = tmp_path / "results"
    (results_dir / "signals").mkdir(parents=True, exist_ok=True)
    (results_dir / "backtest").mkdir(parents=True, exist_ok=True)
    (results_dir / "notebooks").mkdir(parents=True, exist_ok=True)
    (results_dir / "signals" / "latest_ranking.json").write_text(
        '{"as_of": "2026-04-21", "rankings": []}'
    )
    (results_dir / "backtest" / "summary.json").write_text(
        '{"generated_at": "2026-04-21T00:00:00+07:00"}'
    )
    (results_dir / "backtest" / "equity_curve.json").write_text('{"series": []}')
    (results_dir / "backtest" / "annual_returns.json").write_text("{}")
    return results_dir


@fixture
def client(
    tmp_results: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[object, None, None]:
    """Create a FastAPI test client configured for public mode."""
    # Set env vars BEFORE importing api.main — the Settings singleton
    # reads env vars at import time and is frozen afterward.
    monkeypatch.setenv("CSM_PUBLIC_MODE", "true")
    monkeypatch.setenv("CSM_RESULTS_DIR", str(tmp_results))
    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))

    # csm.config.__init__ re-exports `settings`, so `import csm.config.settings`
    # returns the Settings instance, not the module. Use sys.modules instead.
    import sys  # noqa: PLC0415

    _settings_mod: object = sys.modules["csm.config.settings"]
    _original_settings: object = _settings_mod.settings  # type: ignore[attr-defined]
    _settings_mod.settings = Settings()  # type: ignore[attr-defined]

    # api.main and api.deps have ``from csm.config.settings import
    # settings`` which creates local bindings — both must be patched.
    import api.deps as _api_deps  # noqa: PLC0415
    import api.main as _api_main  # noqa: PLC0415

    _original_deps_settings = _api_deps.settings
    _original_main_settings = _api_main.settings
    _api_deps.settings = _settings_mod.settings
    _api_main.settings = _settings_mod.settings
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415

        _api_deps.set_store(ParquetStore(tmp_path / "data" / "processed"))
        (tmp_path / "results" / ".tmp" / "jobs").mkdir(parents=True, exist_ok=True)
        with TestClient(_api_main.app) as test_client:
            yield test_client
    finally:
        _api_deps.settings = _original_deps_settings
        _api_main.settings = _original_main_settings
        _settings_mod.settings = _original_settings  # type: ignore[attr-defined]


@fixture
def private_store(tmp_path: Path) -> ParquetStore:
    """Create a populated ParquetStore for private-mode integration tests.

    Populates universe_latest, portfolio_current, and portfolio_state
    with synthetic data so private-mode endpoint tests can exercise
    the full read path without depending on real pipeline artifacts.
    """
    store = ParquetStore(tmp_path / "data" / "processed")

    universe_df = pd.DataFrame(
        {
            "symbol": ["SET001", "SET002", "SET003"],
            "sector": ["BANK", "TECH", "ENERGY"],
        }
    )
    store.save("universe_latest", universe_df)

    portfolio_df = pd.DataFrame(
        {
            "symbol": ["SET001", "SET002"],
            "weight": [0.6, 0.4],
            "sector": ["BANK", "TECH"],
        }
    )
    store.save("portfolio_current", portfolio_df)

    state_df = pd.DataFrame(
        [
            {
                "regime": "BULL",
                "breaker_state": "NORMAL",
                "equity_fraction": 1.0,
            }
        ]
    )
    store.save("portfolio_state", state_df)

    # Minimal data so the backtest router accepts submissions.
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=60, freq="B", tz="Asia/Bangkok")
    symbols = ["SET001", "SET002", "SET003"]
    prices_data: dict[str, np.ndarray] = {}
    for sym in symbols:
        returns = rng.normal(0.0005, 0.015, size=len(dates))
        prices_data[sym] = 100.0 * np.exp(np.cumsum(returns))
    prices_df = pd.DataFrame(prices_data, index=dates)
    store.save("prices_latest", prices_df)

    features_rows: list[dict[str, object]] = []
    for date in dates:
        for sym in symbols:
            features_rows.append(
                {
                    "date": date,
                    "symbol": sym,
                    "mom_12_1": rng.normal(0.05, 0.15),
                }
            )
    features_df = pd.DataFrame(features_rows)
    store.save("features_latest", features_df)

    return store


@fixture
def private_client(
    tmp_path: Path,
    private_store: ParquetStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[object, None, None]:
    """Create a FastAPI TestClient configured for private mode.

    Uses the populated private_store so read endpoints return real data.
    """
    monkeypatch.setenv("CSM_PUBLIC_MODE", "false")
    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CSM_RESULTS_DIR", str(tmp_path / "results"))

    # StaticFiles mount requires the notebooks directory to exist at import time.
    (tmp_path / "results" / "notebooks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / ".tmp" / "jobs").mkdir(parents=True, exist_ok=True)

    import sys  # noqa: PLC0415

    _settings_mod: object = sys.modules["csm.config.settings"]
    _original_settings: object = _settings_mod.settings  # type: ignore[attr-defined]
    _settings_mod.settings = Settings()  # type: ignore[attr-defined]

    import api.deps as _api_deps  # noqa: PLC0415
    import api.main as _api_main  # noqa: PLC0415

    _original_deps_settings = _api_deps.settings
    _original_main_settings = _api_main.settings
    _api_deps.settings = _settings_mod.settings
    _api_main.settings = _settings_mod.settings
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415

        _api_deps.set_store(private_store)
        with TestClient(_api_main.app) as test_client:
            yield test_client
    finally:
        _api_deps.settings = _original_deps_settings
        _api_main.settings = _original_main_settings
        _settings_mod.settings = _original_settings  # type: ignore[attr-defined]


@fixture
def empty_store(tmp_path: Path) -> ParquetStore:
    """Create an empty ParquetStore — no keys saved. Used for 404 tests."""
    return ParquetStore(tmp_path / "data" / "processed")


@fixture
def empty_store_client(
    tmp_path: Path,
    empty_store: ParquetStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[object, None, None]:
    """Create a FastAPI TestClient wired to an empty ParquetStore.

    All read endpoints that depend on store data will return 404.
    """
    monkeypatch.setenv("CSM_PUBLIC_MODE", "false")
    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CSM_RESULTS_DIR", str(tmp_path / "results"))

    (tmp_path / "results" / "notebooks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / ".tmp" / "jobs").mkdir(parents=True, exist_ok=True)

    import sys  # noqa: PLC0415

    _settings_mod: object = sys.modules["csm.config.settings"]
    _original_settings: object = _settings_mod.settings  # type: ignore[attr-defined]
    _settings_mod.settings = Settings()  # type: ignore[attr-defined]

    import api.deps as _api_deps  # noqa: PLC0415
    import api.main as _api_main  # noqa: PLC0415

    _original_deps_settings = _api_deps.settings
    _original_main_settings = _api_main.settings
    _api_deps.settings = _settings_mod.settings
    _api_main.settings = _settings_mod.settings
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415

        _api_deps.set_store(empty_store)
        with TestClient(_api_main.app) as test_client:
            yield test_client
    finally:
        _api_deps.settings = _original_deps_settings
        _api_main.settings = _original_main_settings
        _settings_mod.settings = _original_settings  # type: ignore[attr-defined]
