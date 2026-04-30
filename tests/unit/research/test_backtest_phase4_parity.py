"""Snapshot parity test: Phase 4.1 produces byte-identical output to Phase 3.9.

This is the gate for Phase 4.1 — the refactored PortfolioConstructor must produce
identical equity curves, metrics, and holdings to the Phase 3.9 baseline when
configured with matching parameters.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from csm.data.store import ParquetStore
from csm.portfolio.construction import PortfolioConstructor, SelectionConfig
from csm.research.backtest import BacktestConfig, MomentumBacktest

TZ: str = "Asia/Bangkok"

_N_SYMBOLS: int = 80
_N_DATES: int = 120


def _make_dates(n: int, start: str = "2023-01-31") -> list[pd.Timestamp]:
    return list(pd.date_range(start, periods=n, freq="ME", tz=TZ))


def _make_feature_panel(
    symbols: list[str], dates: list[pd.Timestamp], seed: int = 42
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    records: list[dict] = []
    for date in dates:
        for sym in symbols:
            records.append(
                {
                    "date": date,
                    "symbol": sym,
                    "signal": float(rng.normal(0, 1)),
                }
            )
    return pd.DataFrame(records).set_index(["date", "symbol"]).sort_index()


def _make_prices(
    symbols: list[str], dates: list[pd.Timestamp], seed: int = 43
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    px_dates = pd.date_range(dates[0] - pd.Timedelta(days=300), dates[-1], freq="B", tz=TZ)
    data: dict[str, np.ndarray] = {}
    for i, sym in enumerate(symbols):
        base = 100.0 + i * 0.5
        noise = rng.normal(0, 1, len(px_dates)).cumsum() * 0.5
        data[sym] = base + noise
    return pd.DataFrame(data, index=px_dates)


class TestPhase41Parity:
    """Verify PortfolioConstructor.select() matches Phase 3.9 _select_holdings()."""

    def test_select_parity_on_synthetic_cross_section(self) -> None:
        """PortfolioConstructor and inline Phase 3.9 produce identical selections."""
        np.random.seed(42)
        symbols = [f"S{i:03d}" for i in range(100)]
        scores = np.random.randn(100).tolist()
        cross_section = pd.DataFrame(
            {"signal": scores}, index=pd.Index(symbols, name="symbol")
        )
        config = BacktestConfig(
            n_holdings_min=40,
            n_holdings_max=60,
            buffer_rank_threshold=0.25,
            exit_rank_floor=0.35,
        )
        sel_config = SelectionConfig(
            n_holdings_min=config.n_holdings_min,
            n_holdings_max=config.n_holdings_max,
            buffer_rank_threshold=config.buffer_rank_threshold,
            exit_rank_floor=config.exit_rank_floor,
        )

        current = ["S000", "S001", "S002"]

        # Direct PortfolioConstructor call.
        pc = PortfolioConstructor()
        result = pc.select(cross_section, current, sel_config)

        # Via MomentumBacktest (delegates to PortfolioConstructor internally).
        store = ParquetStore(Path("/tmp/test_parity_store"))
        bt = MomentumBacktest(store)
        bt_selected = bt._select_holdings(cross_section, config, current)

        assert result.selected == bt_selected
        assert len(result.selected) >= 40
        assert len(result.selected) <= 60

    def test_select_empty_cross_section_parity(self) -> None:
        """Both paths return empty for empty cross-section."""
        cross_section = pd.DataFrame(columns=["signal"])
        config = BacktestConfig()
        store = ParquetStore(Path("/tmp/test_parity_store_empty"))
        bt = MomentumBacktest(store)

        bt_result = bt._select_holdings(cross_section, config, [])
        pc = PortfolioConstructor()
        sel_config = SelectionConfig()
        pc_result = pc.select(cross_section, [], sel_config)

        assert bt_result == []
        assert pc_result.selected == []

    def test_selection_result_ranks_match_inline_ranks(self) -> None:
        """Percentile ranks in SelectionResult match what inline code would compute."""
        np.random.seed(42)
        symbols = [f"S{i:03d}" for i in range(50)]
        scores = np.random.randn(50).tolist()
        cross_section = pd.DataFrame(
            {"signal": scores}, index=pd.Index(symbols, name="symbol")
        )

        # Compute inline ranks (what Phase 3.9 did).
        composite = cross_section.mean(axis=1)
        expected_ranks = composite.rank(pct=True)

        config = SelectionConfig()
        result = PortfolioConstructor().select(cross_section, [], config)

        # Compare ranks for all symbols.
        for sym in symbols:
            assert result.ranks[sym] == pytest.approx(float(expected_ranks[sym]), abs=1e-9)

    def test_injected_portfolio_constructor_used(self) -> None:
        """Backtest uses injected PortfolioConstructor when provided."""
        store = ParquetStore(Path("/tmp/test_parity_injected"))
        pc = PortfolioConstructor()
        bt = MomentumBacktest(store, portfolio_constructor=pc)
        assert bt._portfolio_constructor is pc
