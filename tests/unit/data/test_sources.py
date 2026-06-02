"""Tests for the OHLCV source factory and the CSM_OHLCV_SOURCE flag."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from csm.config.settings import Settings
from csm.data.engine_loader import MarketDataEngineLoader
from csm.data.loader import OHLCVLoader
from csm.data.sources import OHLCVSource, build_ohlcv_loader


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in ("CSM_OHLCV_SOURCE", "CSM_MARKET_DATA_ENGINE_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings()


class TestFactory:
    def test_default_is_db_engine_loader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Since Phase 5 (2026-06-02), the default OHLCV source is 'db'."""
        settings = _settings(
            monkeypatch, CSM_MARKET_DATA_ENGINE_BASE_URL="http://marketdata.test:8000"
        )
        loader = build_ohlcv_loader(settings)
        assert isinstance(loader, MarketDataEngineLoader)
        assert isinstance(loader, OHLCVSource)

    def test_explicit_parquet_is_tvkit_loader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = _settings(monkeypatch, CSM_OHLCV_SOURCE="parquet")
        assert isinstance(build_ohlcv_loader(settings), OHLCVLoader)

    def test_db_is_engine_loader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = _settings(
            monkeypatch,
            CSM_OHLCV_SOURCE="db",
            CSM_MARKET_DATA_ENGINE_BASE_URL="http://marketdata.test:8000",
        )
        loader = build_ohlcv_loader(settings)
        assert isinstance(loader, MarketDataEngineLoader)
        assert isinstance(loader, OHLCVSource)


class TestValidators:
    def test_invalid_source_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ValidationError, match="ohlcv_source"):
            _settings(monkeypatch, CSM_OHLCV_SOURCE="redis")

    def test_db_requires_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ValidationError, match="MARKET_DATA_ENGINE_BASE_URL"):
            _settings(monkeypatch, CSM_OHLCV_SOURCE="db")
