"""Unit tests for the quality-first universe filter."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from csm.portfolio.quality_filter import (
    QualityFilter,
    QualityFilterConfig,
    QualityFilterResult,
)


@pytest.fixture
def quality_filter() -> QualityFilter:
    return QualityFilter()


@pytest.fixture
def symbols() -> list[str]:
    return ["A", "B", "C", "D", "E"]


@pytest.fixture
def good_fundamental_data() -> dict[str, dict[str, float]]:
    return {
        "A": {"earnings": 100.0, "net_profit_margin": 0.15},
        "B": {"earnings": 50.0, "net_profit_margin": 0.08},
        "C": {"earnings": 200.0, "net_profit_margin": 0.20},
        "D": {"earnings": 10.0, "net_profit_margin": 0.02},
        "E": {"earnings": 75.0, "net_profit_margin": 0.12},
    }


@pytest.fixture
def price_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=252, freq="B")
    rng = np.random.default_rng(42)
    data: dict[str, np.ndarray] = {}
    for sym in ["A", "B", "C", "D", "E", "F", "G"]:
        data[sym] = 100.0 * np.exp(np.cumsum(rng.normal(0.0006, 0.012, len(dates))))
    return pd.DataFrame(data, index=dates)


# ── Config validation ──────────────────────────────────────────────────


class TestQualityFilterConfig:
    def test_defaults(self) -> None:
        cfg = QualityFilterConfig()
        assert cfg.enabled is True
        assert cfg.require_positive_earnings is True
        assert cfg.min_net_profit_margin == 0.0

    def test_negative_npm_allowed(self) -> None:
        cfg = QualityFilterConfig(min_net_profit_margin=-0.05)
        assert cfg.min_net_profit_margin == -0.05


# ── Disabled pass-through ──────────────────────────────────────────────


class TestDisabled:
    def test_disabled_returns_all_symbols(
        self, quality_filter: QualityFilter, symbols: list[str]
    ) -> None:
        cfg = QualityFilterConfig(enabled=False)
        passed, result = quality_filter.apply(symbols, cfg)
        assert passed == symbols
        assert result.n_before == len(symbols)
        assert result.n_after == len(symbols)
        assert result.n_filtered == 0


# ── Fundamental path ───────────────────────────────────────────────────


class TestFundamentalPath:
    def test_all_pass(
        self,
        quality_filter: QualityFilter,
        symbols: list[str],
        good_fundamental_data: dict[str, dict[str, float]],
    ) -> None:
        cfg = QualityFilterConfig()
        passed, result = quality_filter.apply(
            symbols,
            cfg,
            fundamental_data=good_fundamental_data,
        )
        assert passed == symbols
        assert result.n_filtered == 0

    def test_filters_negative_earnings(
        self,
        quality_filter: QualityFilter,
        symbols: list[str],
        good_fundamental_data: dict[str, dict[str, float]],
    ) -> None:
        data = {**good_fundamental_data, "C": {"earnings": -50.0, "net_profit_margin": 0.05}}
        cfg = QualityFilterConfig()
        passed, result = quality_filter.apply(
            symbols,
            cfg,
            fundamental_data=data,
        )
        assert "C" not in passed
        assert result.n_filtered == 1
        assert "negative_earnings" in result.filtered_reasons

    def test_filters_low_margin(
        self,
        quality_filter: QualityFilter,
        symbols: list[str],
        good_fundamental_data: dict[str, dict[str, float]],
    ) -> None:
        cfg = QualityFilterConfig(min_net_profit_margin=0.10)
        passed, result = quality_filter.apply(
            symbols,
            cfg,
            fundamental_data=good_fundamental_data,
        )
        assert "D" not in passed  # NPM = 0.02
        assert "B" not in passed  # NPM = 0.08
        assert "low_profit_margin" in result.filtered_reasons

    def test_missing_fundamental_data(
        self,
        quality_filter: QualityFilter,
        symbols: list[str],
    ) -> None:
        partial = {"A": {"earnings": 100.0, "net_profit_margin": 0.15}}
        cfg = QualityFilterConfig()
        passed, result = quality_filter.apply(
            symbols,
            cfg,
            fundamental_data=partial,
        )
        assert passed == ["A"]
        assert result.n_filtered == 4
        assert "no_fundamental_data" in result.filtered_reasons


# ── Synthetic proxy path ───────────────────────────────────────────────


class TestSyntheticProxy:
    def test_filters_negative_trailing_return(
        self,
        quality_filter: QualityFilter,
        price_data: pd.DataFrame,
    ) -> None:
        # Manually force symbol "F" to have a negative 126d return
        forced = price_data.copy()
        forced["F"] = forced["F"].iloc[0] * np.exp(-np.linspace(0.0, 0.4, len(forced)))
        symbols = ["A", "B", "C", "D", "E", "F"]
        cfg = QualityFilterConfig(synthetic_quality_threshold=0.0)
        passed, result = quality_filter.apply(
            symbols,
            cfg,
            price_data=forced,
        )
        assert len(passed) < len(symbols)
        assert "negative_trailing_return" in result.filtered_reasons

    def test_all_pass_with_positive_returns(
        self,
        quality_filter: QualityFilter,
        price_data: pd.DataFrame,
    ) -> None:
        symbols = ["A", "B", "C"]
        cfg = QualityFilterConfig(synthetic_quality_threshold=-1.0)
        passed, result = quality_filter.apply(
            symbols,
            cfg,
            price_data=price_data,
        )
        assert len(passed) == len(symbols)
        assert result.n_filtered == 0

    def test_insufficient_price_data(
        self,
        quality_filter: QualityFilter,
        symbols: list[str],
    ) -> None:
        short = pd.DataFrame({"A": [100, 101, 102]})
        cfg = QualityFilterConfig()
        passed, result = quality_filter.apply(
            symbols,
            cfg,
            price_data=short,
        )
        assert passed == symbols  # pass-through when too short


# ── No data fallback ───────────────────────────────────────────────────


class TestNoDataFallback:
    def test_no_data_pass_through(
        self,
        quality_filter: QualityFilter,
        symbols: list[str],
    ) -> None:
        cfg = QualityFilterConfig()
        passed, result = quality_filter.apply(symbols, cfg)
        assert passed == symbols
        assert result.n_filtered == 0
