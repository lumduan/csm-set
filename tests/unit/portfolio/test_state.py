"""Tests for Phase 4 state models."""

import pandas as pd
import pytest
from pydantic import ValidationError

from csm.portfolio.state import (
    CircuitBreakerState,
    OverlayContext,
    OverlayJournalEntry,
    PortfolioState,
)
from csm.risk.regime import RegimeState

TZ: str = "Asia/Bangkok"


class TestCircuitBreakerState:
    def test_default_is_normal(self) -> None:
        assert CircuitBreakerState.NORMAL == "NORMAL"
        assert str(CircuitBreakerState.NORMAL) == "NORMAL"


class TestOverlayJournalEntry:
    def test_minimal_entry(self) -> None:
        entry = OverlayJournalEntry(
            overlay="TestOverlay",
            asof=pd.Timestamp("2024-01-31", tz=TZ),
            decision="test decision",
        )
        assert entry.overlay == "TestOverlay"
        assert entry.inputs == {}
        assert entry.outputs == {}

    def test_full_entry(self) -> None:
        entry = OverlayJournalEntry(
            overlay="VolScalingOverlay",
            asof=pd.Timestamp("2024-01-31", tz=TZ),
            decision="Reduced equity fraction to 0.75",
            inputs={"realised_vol": 0.20, "target_vol": 0.15},
            outputs={"equity_fraction": 0.75},
        )
        assert entry.overlay == "VolScalingOverlay"
        assert entry.inputs["realised_vol"] == 0.20
        assert entry.outputs["equity_fraction"] == 0.75

    def test_asof_required(self) -> None:
        with pytest.raises(ValidationError):
            OverlayJournalEntry(overlay="Test", decision="test")  # type: ignore[arg-type]


class TestPortfolioState:
    def test_defaults(self) -> None:
        state = PortfolioState(
            asof=pd.Timestamp("2024-01-31", tz=TZ),
            target_weights={},
            regime=RegimeState.BULL,
        )
        assert state.equity_fraction == 1.0
        assert state.breaker_state == CircuitBreakerState.NORMAL
        assert state.journal == []

    def test_with_weights_and_journal(self) -> None:
        entry = OverlayJournalEntry(
            overlay="PortfolioConstructor",
            asof=pd.Timestamp("2024-01-31", tz=TZ),
            decision="Selected 50 holdings",
            inputs={"n_candidates": 60},
            outputs={"n_selected": 50},
        )
        state = PortfolioState(
            asof=pd.Timestamp("2024-01-31", tz=TZ),
            target_weights={"A": 0.02, "B": 0.02},
            equity_fraction=0.85,
            regime=RegimeState.BEAR,
            journal=[entry],
        )
        assert len(state.target_weights) == 2
        assert state.target_weights["A"] == 0.02
        assert state.equity_fraction == 0.85
        assert state.regime == RegimeState.BEAR
        assert len(state.journal) == 1

    def test_equity_fraction_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioState(
                asof=pd.Timestamp("2024-01-31", tz=TZ),
                equity_fraction=-0.1,  # type: ignore[arg-type]
            )


class TestOverlayContext:
    def test_construction_with_valid_data(self) -> None:
        dates = pd.date_range("2024-01-01", periods=63, freq="B", tz=TZ)
        prices = pd.DataFrame(
            {"A": range(63), "B": range(63, 126)},
            index=dates,
        )
        volumes = prices * 1000
        index_prices = pd.Series(range(63), index=dates)
        equity = pd.Series(1.0, index=dates)

        ctx = OverlayContext(
            prices_window=prices,
            volumes_window=volumes,
            index_prices_window=index_prices,
            equity_curve_to_date=equity,
        )
        assert ctx.sector_map == {}
        assert ctx.prices_window.shape == (63, 2)

    def test_sector_map_defaults_to_empty(self) -> None:
        dates = pd.date_range("2024-01-01", periods=10, freq="B", tz=TZ)
        prices = pd.DataFrame({"A": range(10)}, index=dates)
        equity = pd.Series(1.0, index=dates)

        ctx = OverlayContext(
            prices_window=prices,
            volumes_window=prices,
            index_prices_window=pd.Series(range(10), index=dates),
            equity_curve_to_date=equity,
        )
        assert ctx.sector_map == {}
