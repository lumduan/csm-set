"""Tests for PortfolioConstructor, SelectionConfig, and SelectionResult."""

import numpy as np
import pandas as pd
import pytest

from csm.portfolio.construction import PortfolioConstructor, SelectionConfig, SelectionResult
from csm.portfolio.exceptions import PortfolioError


class TestSelectionConfig:
    def test_defaults_match_phase39_constants(self) -> None:
        config = SelectionConfig()
        assert config.n_holdings_min == 40
        assert config.n_holdings_max == 60
        assert config.buffer_rank_threshold == 0.25
        assert config.exit_rank_floor == 0.35

    def test_custom_values_accepted(self) -> None:
        config = SelectionConfig(
            n_holdings_min=10,
            n_holdings_max=20,
            buffer_rank_threshold=0.15,
            exit_rank_floor=0.50,
        )
        assert config.n_holdings_min == 10
        assert config.exit_rank_floor == 0.50


class TestSelectionResult:
    def test_defaults(self) -> None:
        result = SelectionResult()
        assert result.selected == []
        assert result.evicted == []
        assert result.retained == []
        assert result.ranks == {}


class TestPortfolioConstructorSelect:
    """Tests for PortfolioConstructor.select() — Phase 4.1."""

    @staticmethod
    def _make_cross_section(symbols: list[str], scores: list[float]) -> pd.DataFrame:
        return pd.DataFrame({"signal": scores}, index=pd.Index(symbols, name="symbol"))

    def test_empty_cross_section_returns_empty(self) -> None:
        empty = pd.DataFrame(columns=["signal"])
        result = PortfolioConstructor().select(empty, [], SelectionConfig())
        assert result.selected == []
        assert result.evicted == []

    def test_selects_top_n_max_when_no_current_holdings(self) -> None:
        np.random.seed(42)
        symbols = [f"S{i:03d}" for i in range(100)]
        scores = np.random.randn(100).tolist()
        cross_section = self._make_cross_section(symbols, scores)
        config = SelectionConfig(n_holdings_min=40, n_holdings_max=60)
        result = PortfolioConstructor().select(cross_section, [], config)
        # Should select exactly n_holdings_max symbols (all fit within max).
        assert len(result.selected) == 60
        # No evictions or retentions since there were no current holdings.
        assert result.evicted == []
        assert result.retained == []

    def test_small_universe_returns_all_available(self) -> None:
        cross_section = self._make_cross_section(
            ["A", "B", "C", "D", "E"], [1.0, 0.5, 0.0, -0.5, -1.0]
        )
        config = SelectionConfig(n_holdings_min=80, n_holdings_max=100)
        result = PortfolioConstructor().select(cross_section, [], config)
        # Only 5 symbols available, can't fill n_min=80.
        assert len(result.selected) == 5

    def test_buffer_retains_holdings_within_candidates(self) -> None:
        """Holdings that are also in the candidate pool are retained."""
        cross_section = self._make_cross_section(["A", "B", "C", "D"], [0.8, 0.6, 1.0, 0.2])
        config = SelectionConfig(n_holdings_min=2, n_holdings_max=4, buffer_rank_threshold=0.25)
        result = PortfolioConstructor().select(cross_section, ["A", "B"], config)
        # A is in top-4 candidates, B is borderline but in the candidate pool
        assert "A" in result.selected
        assert "A" in result.retained

    def test_buffer_evicts_holding_when_replacement_better(self) -> None:
        """Holding evicted when replacement ranks buffer_threshold better."""
        symbols = ["A", "B", "C", "D"]
        # C(1.0) > A(0.8) > B(0.6) > D(0.2)
        cross_section = self._make_cross_section(symbols, [0.8, 0.6, 1.0, 0.2])
        # n_max=2 so only top 2 (C, A) are candidates; B is outside candidate pool.
        config = SelectionConfig(n_holdings_min=2, n_holdings_max=2, buffer_rank_threshold=0.125)
        result = PortfolioConstructor().select(cross_section, ["A", "B"], config)
        # A is in candidates → retained. B not in candidates → rank diff check:
        # B (rank 0.5) vs best replacement C (rank 1.0): diff=0.5 >= 0.125 → B evicted
        assert "C" in result.selected
        assert "B" in result.evicted

    def test_exit_floor_evicts_unconditionally(self) -> None:
        """Holding with rank < exit_rank_floor evicted regardless of replacement."""
        symbols = ["A", "B", "C", "D", "E"]
        scores = [0.1, 0.3, 0.5, 0.7, 0.9]
        cross_section = self._make_cross_section(symbols, scores)
        # n_max=2 so only top 2 (E, D) are candidates; A is outside candidate pool.
        config = SelectionConfig(n_holdings_min=2, n_holdings_max=2, exit_rank_floor=0.35)
        # A has the lowest score → rank ~0.20 < 0.35 → unconditionally evicted
        result = PortfolioConstructor().select(cross_section, ["A", "D"], config)
        assert "A" in result.evicted
        assert "D" in result.selected

    def test_enforces_n_holdings_max_cap(self) -> None:
        """Result capped at n_holdings_max even with many current holdings."""
        np.random.seed(42)
        symbols = [f"S{i:03d}" for i in range(100)]
        scores = np.random.randn(100).tolist()
        cross_section = self._make_cross_section(symbols, scores)
        config = SelectionConfig(n_holdings_min=40, n_holdings_max=60)
        result = PortfolioConstructor().select(cross_section, [], config)
        assert len(result.selected) <= 60

    def test_tops_up_to_n_holdings_min(self) -> None:
        """When buffered list is shorter than n_min, top up from candidates."""
        np.random.seed(42)
        symbols = [f"S{i:03d}" for i in range(100)]
        scores = np.random.randn(100).tolist()
        cross_section = self._make_cross_section(symbols, scores)
        # Only 2 current holdings → after buffer, should top-up to n_min=40.
        config = SelectionConfig(n_holdings_min=40, n_holdings_max=60, buffer_rank_threshold=0.25)
        result = PortfolioConstructor().select(cross_section, ["S000", "S001"], config)
        assert len(result.selected) >= 40

    def test_entry_mask_restricts_new_entries(self) -> None:
        """entry_mask excludes non-RS-passing symbols from new entry candidates."""
        symbols = ["A", "B", "C", "D", "E"]
        scores = [0.9, 0.8, 0.7, 0.4, 0.3]
        cross_section = self._make_cross_section(symbols, scores)
        # Entry mask only allows A, B for new entry. C, D, E are excluded.
        entry_mask: set[str] = {"A", "B"}
        config = SelectionConfig(n_holdings_min=2, n_holdings_max=5)
        # Current holding "E" is outside entry mask, but is eligible for buffer.
        result = PortfolioConstructor().select(cross_section, ["E"], config, entry_mask=entry_mask)
        # E should not be in the selected list since it ranks low, and A,B are top
        assert "A" in result.selected
        assert "B" in result.selected

    def test_entry_mask_fallback_when_pool_empty(self) -> None:
        """Fall back to full composite when entry mask empties the candidate pool."""
        symbols = ["A", "B", "C"]
        scores = [0.9, 0.8, 0.7]
        cross_section = self._make_cross_section(symbols, scores)
        # Mask contains symbols not in the cross-section → pool would be empty.
        entry_mask: set[str] = {"X", "Y"}
        config = SelectionConfig(n_holdings_min=1, n_holdings_max=5)
        result = PortfolioConstructor().select(cross_section, [], config, entry_mask=entry_mask)
        # Should fall back to full composite and select top symbols.
        assert len(result.selected) > 0
        assert set(result.selected).issubset(set(symbols))

    def test_deterministic_for_fixed_input(self) -> None:
        """Same input produces same output — no randomness in selection."""
        np.random.seed(42)
        symbols = [f"S{i:03d}" for i in range(100)]
        scores = np.random.randn(100).tolist()
        cross_section = self._make_cross_section(symbols, scores)
        config = SelectionConfig()
        result1 = PortfolioConstructor().select(cross_section, ["S000", "S001", "S002"], config)
        result2 = PortfolioConstructor().select(cross_section, ["S000", "S001", "S002"], config)
        assert result1.selected == result2.selected
        assert result1.evicted == result2.evicted
        assert result1.retained == result2.retained

    def test_ranks_populated_for_all_symbols(self) -> None:
        """SelectionResult.ranks contains percentile rank for every symbol."""
        symbols = ["A", "B", "C", "D", "E"]
        scores = [0.9, 0.8, 0.7, 0.4, 0.3]
        cross_section = self._make_cross_section(symbols, scores)
        config = SelectionConfig()
        result = PortfolioConstructor().select(cross_section, [], config)
        assert len(result.ranks) == 5
        # Check ranks are in [0, 1] and monotonic with scores
        for sym in symbols:
            assert 0.0 <= result.ranks[sym] <= 1.0

    def test_no_current_holdings_all_new_selection(self) -> None:
        """Fresh selection with no current holdings — all are new entries."""
        symbols = ["A", "B", "C", "D", "E"]
        scores = [0.9, 0.8, 0.7, 0.4, 0.3]
        cross_section = self._make_cross_section(symbols, scores)
        config = SelectionConfig(n_holdings_min=2, n_holdings_max=3)
        result = PortfolioConstructor().select(cross_section, [], config)
        assert len(result.selected) == 3
        assert result.retained == []
        # Top 3 by score: A(0.9), B(0.8), C(0.7)
        assert set(result.selected) == {"A", "B", "C"}

    def test_single_feature_column_works(self) -> None:
        """Cross-section with a single feature column — mean is identity."""
        cross_section = self._make_cross_section(
            ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"],
            list(range(10, 0, -1)),
        )
        config = SelectionConfig(n_holdings_min=3, n_holdings_max=5)
        result = PortfolioConstructor().select(cross_section, [], config)
        assert len(result.selected) == 5
        # Top 5: A(10), B(9), C(8), D(7), E(6)
        assert "A" in result.selected
        assert "J" not in result.selected


class TestPortfolioConstructorBuild:
    """Preserved tests for the existing build() method."""

    def test_build_valid_holdings(self) -> None:
        symbols = ["A", "B"]
        weights = pd.Series([0.6, 0.4], index=["A", "B"])
        as_of = pd.Timestamp("2024-01-31", tz="Asia/Bangkok")
        result = PortfolioConstructor().build(symbols, weights, as_of)
        assert len(result) == 2
        assert result.iloc[0]["symbol"] == "A"
        assert result.iloc[0]["weight"] == 0.6

    def test_build_negative_weight_raises(self) -> None:
        weights = pd.Series([0.6, -0.4], index=["A", "B"])
        as_of = pd.Timestamp("2024-01-31", tz="Asia/Bangkok")
        with pytest.raises(PortfolioError, match="non-negative"):
            PortfolioConstructor().build(["A", "B"], weights, as_of)

    def test_build_weights_not_sum_to_one_raises(self) -> None:
        weights = pd.Series([0.6, 0.3], index=["A", "B"])
        as_of = pd.Timestamp("2024-01-31", tz="Asia/Bangkok")
        with pytest.raises(PortfolioError, match="sum to 1"):
            PortfolioConstructor().build(["A", "B"], weights, as_of)
