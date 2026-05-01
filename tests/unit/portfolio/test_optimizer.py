"""Tests for portfolio optimizers."""

import logging

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from csm.portfolio.exceptions import OptimizationError
from csm.portfolio.optimizer import OptimizerConfig, WeightOptimizer, WeightScheme


@pytest.fixture
def small_prices() -> pd.DataFrame:
    """5 symbols x 100 days of synthetic prices with differentiated volatility."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=100, freq="B", tz="Asia/Bangkok")
    symbols = ["A", "B", "C", "D", "E"]
    vols = [0.01, 0.02, 0.03, 0.04, 0.05]
    data: dict[str, np.ndarray] = {}
    for sym, vol in zip(symbols, vols, strict=True):
        data[sym] = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, vol, len(dates)), axis=0))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def skewed_vol_prices() -> pd.DataFrame:
    """12 symbols x 200 days; symbol 'LOWVOL' has near-constant price (very low vol)."""
    rng = np.random.default_rng(99)
    dates = pd.date_range("2023-01-01", periods=200, freq="B", tz="Asia/Bangkok")
    n = 12
    symbols = ["LOWVOL"] + [f"S{i:02d}" for i in range(1, n)]
    data: dict[str, np.ndarray] = {}
    for i, sym in enumerate(symbols):
        vol = 0.001 if sym == "LOWVOL" else 0.025 + 0.005 * i
        data[sym] = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, vol, len(dates)), axis=0))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def floor_test_prices() -> pd.DataFrame:
    """40 symbols x 200 days with highly varied volatilities (some very high)."""
    rng = np.random.default_rng(123)
    dates = pd.date_range("2023-01-01", periods=200, freq="B", tz="Asia/Bangkok")
    n = 40
    symbols = [f"F{i:02d}" for i in range(n)]
    data: dict[str, np.ndarray] = {}
    for i, sym in enumerate(symbols):
        # First 5 symbols have very high vol → near-zero inverse-vol weight
        vol = 0.15 if i < 5 else 0.02
        data[sym] = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, vol, len(dates)), axis=0))
    return pd.DataFrame(data, index=dates)


class TestWeightScheme:
    def test_enum_values(self) -> None:
        assert WeightScheme.EQUAL == "equal"
        assert WeightScheme.INVERSE_VOL == "inverse_vol"
        assert WeightScheme.VOL_TARGET == "vol_target"
        assert WeightScheme.MIN_VARIANCE == "min_variance"
        assert str(WeightScheme.EQUAL) == "equal"
        assert WeightScheme("vol_target") is WeightScheme.VOL_TARGET


class TestOptimizerConfig:
    def test_defaults(self) -> None:
        config = OptimizerConfig()
        assert config.min_position == pytest.approx(0.05)
        assert config.max_position == pytest.approx(0.15)
        assert config.vol_lookback_days == 63
        assert config.target_position_vol == pytest.approx(0.15)
        assert config.solver_max_iter == 1000

    def test_bounds_enforced(self) -> None:
        with pytest.raises(ValidationError):
            OptimizerConfig(min_position=-0.1)
        with pytest.raises(ValidationError):
            OptimizerConfig(max_position=1.5)

    def test_range_constraints(self) -> None:
        with pytest.raises(ValidationError):
            OptimizerConfig(vol_lookback_days=10)
        with pytest.raises(ValidationError):
            OptimizerConfig(solver_max_iter=50)


class TestWeightOptimizer:
    def test_equal_weight_sums_to_one(self) -> None:
        weights: pd.Series = WeightOptimizer().equal_weight(["A", "B", "C", "D"])
        assert float(weights.sum()) == pytest.approx(1.0)

    def test_vol_target_output_shape(self, sample_prices: pd.DataFrame) -> None:
        returns: pd.DataFrame = sample_prices[["SET000", "SET001", "SET002"]].pct_change().dropna()
        weights: pd.Series = WeightOptimizer().vol_target_weight(
            ["SET000", "SET001", "SET002"], returns
        )
        assert list(weights.index) == ["SET000", "SET001", "SET002"]


class TestWeightOptimizerCompute:
    def test_compute_equal_weight_sums_to_one(self, small_prices: pd.DataFrame) -> None:
        symbols = ["A", "B", "C", "D"]
        weights = WeightOptimizer().compute(
            symbols,
            small_prices,
            WeightScheme.EQUAL,
            OptimizerConfig(),
        )
        assert float(weights.sum()) == pytest.approx(1.0)
        assert (weights >= 0.0).all()

    def test_compute_equal_weight_snapshot_parity(
        self,
        small_prices: pd.DataFrame,
    ) -> None:
        """EQUAL with [0,1] bounds produces byte-identical result to equal_weight()."""
        symbols = ["A", "B", "C", "D"]
        optimizer = WeightOptimizer()
        config = OptimizerConfig(min_position=0.0, max_position=1.0)
        compute_result = optimizer.compute(symbols, small_prices, WeightScheme.EQUAL, config)
        legacy_result = optimizer.equal_weight(symbols)
        pd.testing.assert_series_equal(compute_result, legacy_result)

    @pytest.mark.parametrize(
        "scheme",
        [
            WeightScheme.EQUAL,
            WeightScheme.INVERSE_VOL,
            WeightScheme.VOL_TARGET,
            WeightScheme.MIN_VARIANCE,
        ],
    )
    def test_compute_empty_symbols(
        self,
        scheme: WeightScheme,
        small_prices: pd.DataFrame,
    ) -> None:
        result = WeightOptimizer().compute([], small_prices, scheme, OptimizerConfig())
        assert isinstance(result, pd.Series)
        assert len(result) == 0
        assert result.dtype == float

    @pytest.mark.parametrize(
        "scheme",
        [
            WeightScheme.EQUAL,
            WeightScheme.INVERSE_VOL,
            WeightScheme.VOL_TARGET,
            WeightScheme.MIN_VARIANCE,
        ],
    )
    def test_compute_single_symbol(
        self,
        scheme: WeightScheme,
        small_prices: pd.DataFrame,
    ) -> None:
        result = WeightOptimizer().compute(
            ["A"],
            small_prices,
            scheme,
            OptimizerConfig(min_position=0.0, max_position=1.0),
        )
        assert float(result["A"]) == pytest.approx(1.0)
        assert float(result.sum()) == pytest.approx(1.0)

    def test_compute_inverse_vol_inverse_relationship(
        self,
        small_prices: pd.DataFrame,
    ) -> None:
        """Higher-vol symbols should get lower weight."""
        symbols = ["A", "B", "C", "D", "E"]
        config = OptimizerConfig(min_position=0.0, max_position=1.0)
        weights = WeightOptimizer().compute(
            symbols,
            small_prices,
            WeightScheme.INVERSE_VOL,
            config,
        )
        # Volatility order from fixture: A < B < C < D < E
        # Inverse-vol should give A (lowest vol) the highest weight
        assert float(weights["A"]) > float(weights["E"])
        assert float(weights.sum()) == pytest.approx(1.0)

    def test_compute_vol_target_invariants(
        self,
        sample_prices: pd.DataFrame,
    ) -> None:
        symbols = ["SET000", "SET001", "SET002", "SET003", "SET004"]
        config = OptimizerConfig(min_position=0.0, max_position=1.0)
        weights = WeightOptimizer().compute(
            symbols,
            sample_prices,
            WeightScheme.VOL_TARGET,
            config,
        )
        assert float(weights.sum()) == pytest.approx(1.0)
        assert (weights >= 0.0).all()
        assert len(weights) == 5

    def test_compute_min_variance_convergence(
        self,
        sample_prices: pd.DataFrame,
    ) -> None:
        symbols = ["SET000", "SET001", "SET002", "SET003", "SET004"]
        config = OptimizerConfig(min_position=0.0, max_position=1.0)
        weights = WeightOptimizer().compute(
            symbols,
            sample_prices,
            WeightScheme.MIN_VARIANCE,
            config,
        )
        assert float(weights.sum()) == pytest.approx(1.0)
        assert (weights >= 0.0).all()
        assert len(weights) == 5

    def test_compute_min_variance_fallback(
        self,
        sample_prices: pd.DataFrame,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When min_variance_weight raises, fall back to inverse-vol with warning."""
        caplog.set_level(logging.WARNING)
        symbols = ["SET000", "SET001", "SET002"]
        prices = sample_prices[symbols]
        optimizer = WeightOptimizer()
        original_minvar = optimizer.min_variance_weight

        def _fail(*args: object, **kwargs: object) -> pd.Series:
            raise OptimizationError("Simulated solver failure")

        optimizer.min_variance_weight = _fail  # type: ignore[assignment]
        try:
            config = OptimizerConfig(min_position=0.0, max_position=1.0)
            weights = optimizer.compute(symbols, prices, WeightScheme.MIN_VARIANCE, config)
        finally:
            optimizer.min_variance_weight = original_minvar

        assert float(weights.sum()) == pytest.approx(1.0)
        assert (weights >= 0.0).all()
        assert any("falling back" in record.message for record in caplog.records)

    def test_compute_position_cap_enforced(
        self,
        skewed_vol_prices: pd.DataFrame,
    ) -> None:
        """12 symbols, LOWVOL gets inverse-vol weight > 0.10; capped to 0.10."""
        symbols = list(skewed_vol_prices.columns)
        config = OptimizerConfig(max_position=0.10, min_position=0.0)
        weights = WeightOptimizer().compute(
            symbols,
            skewed_vol_prices,
            WeightScheme.INVERSE_VOL,
            config,
        )
        assert float(weights.sum()) == pytest.approx(1.0)
        assert (weights <= 0.10 + 1e-9).all()
        # LOWVOL should have been capped — verify it's at or near the cap
        assert float(weights["LOWVOL"]) == pytest.approx(0.10, rel=1e-3)

    def test_compute_position_floor_enforced(
        self,
        floor_test_prices: pd.DataFrame,
    ) -> None:
        """40 symbols with varied vols; high-vol symbols floored to min_position."""
        symbols = list(floor_test_prices.columns)
        config = OptimizerConfig(min_position=0.02, max_position=1.0)
        weights = WeightOptimizer().compute(
            symbols,
            floor_test_prices,
            WeightScheme.INVERSE_VOL,
            config,
        )
        assert float(weights.sum()) == pytest.approx(1.0)
        assert (weights >= 0.02 - 1e-9).all()

    def test_compute_negative_weight_raises(
        self,
        small_prices: pd.DataFrame,
    ) -> None:
        """Mock equal_weight to return a negative value — should raise."""
        symbols = ["A", "B", "C"]
        optimizer = WeightOptimizer()
        original = optimizer.equal_weight

        def _negative(syms: list[str]) -> pd.Series:
            return pd.Series([-0.1, 0.6, 0.5], index=syms, dtype=float)

        optimizer.equal_weight = _negative  # type: ignore[assignment]
        try:
            with pytest.raises(OptimizationError, match="Negative weight"):
                optimizer.compute(
                    symbols,
                    small_prices,
                    WeightScheme.EQUAL,
                    OptimizerConfig(),
                )
        finally:
            optimizer.equal_weight = original

    def test_compute_unknown_scheme_raises(
        self,
        small_prices: pd.DataFrame,
    ) -> None:
        class FakeScheme(str):
            pass

        fake = FakeScheme("bogus")
        with pytest.raises(ValueError, match="Unknown weight scheme"):
            WeightOptimizer().compute(
                ["A"],
                small_prices,
                fake,  # type: ignore[arg-type]
                OptimizerConfig(),
            )


class TestMonteCarloResult:
    def test_default_construction(self) -> None:
        from csm.portfolio.optimizer import MonteCarloResult

        result = MonteCarloResult(
            max_sharpe_weights={"A": 0.5, "B": 0.5},
            max_sharpe_return=0.10,
            max_sharpe_volatility=0.15,
            max_sharpe_ratio=0.667,
            frontier_returns=[0.05, 0.10],
            frontier_volatilities=[0.10, 0.15],
            frontier_sharpes=[0.5, 0.667],
            is_efficient=[False, True],
            equal_weight_return=0.08,
            equal_weight_volatility=0.12,
            equal_weight_sharpe=0.5,
            n_samples=1000,
        )
        assert result.max_sharpe_ratio == pytest.approx(0.667)
        assert result.n_samples == 1000


class TestMonteCarloOptimize:
    def test_max_sharpe_compute_sums_to_one(
        self,
        sample_prices: pd.DataFrame,
    ) -> None:
        symbols = ["SET000", "SET001", "SET002", "SET003", "SET004"]
        config = OptimizerConfig(mc_samples=5_000, min_position=0.0, max_position=1.0)
        weights = WeightOptimizer().compute(
            symbols,
            sample_prices,
            WeightScheme.MAX_SHARPE,
            config,
        )
        assert float(weights.sum()) == pytest.approx(1.0)
        assert (weights >= 0.0).all()

    def test_max_sharpe_compute_long_only(
        self,
        sample_prices: pd.DataFrame,
    ) -> None:
        symbols = [
            "SET000",
            "SET001",
            "SET002",
            "SET003",
            "SET004",
            "SET005",
            "SET006",
            "SET007",
            "SET008",
            "SET009",
        ]
        config = OptimizerConfig(mc_samples=5_000, min_position=0.0, max_position=1.0)
        weights = WeightOptimizer().compute(
            symbols,
            sample_prices,
            WeightScheme.MAX_SHARPE,
            config,
        )
        assert (weights >= -1e-12).all()

    def test_max_sharpe_fallback_on_failure(
        self,
        sample_prices: pd.DataFrame,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Mock _monte_carlo_optimize to raise → falls back to inverse-vol."""
        caplog.set_level(logging.WARNING)
        symbols = ["SET000", "SET001", "SET002"]
        prices = sample_prices[symbols]
        optimizer = WeightOptimizer()
        original = optimizer._monte_carlo_optimize

        def _fail(*args: object, **kwargs: object) -> pd.Series:
            raise OptimizationError("Simulated MC failure")

        optimizer._monte_carlo_optimize = _fail  # type: ignore[assignment]
        try:
            config = OptimizerConfig(min_position=0.0, max_position=1.0)
            weights = optimizer.compute(symbols, prices, WeightScheme.MAX_SHARPE, config)
        finally:
            optimizer._monte_carlo_optimize = original

        assert float(weights.sum()) == pytest.approx(1.0)
        assert any("falling back" in record.message for record in caplog.records)

    def test_max_sharpe_position_constraints_respected(
        self,
        sample_prices: pd.DataFrame,
    ) -> None:
        symbols = [
            "SET000",
            "SET001",
            "SET002",
            "SET003",
            "SET004",
            "SET005",
            "SET006",
            "SET007",
            "SET008",
            "SET009",
        ]
        config = OptimizerConfig(
            mc_samples=5_000,
            min_position=0.03,
            max_position=0.25,
        )
        weights = WeightOptimizer().compute(
            symbols,
            sample_prices,
            WeightScheme.MAX_SHARPE,
            config,
        )
        assert float(weights.sum()) == pytest.approx(1.0)
        # With 10 symbols, 0.03*10=0.30 ≤ 1.0 and 0.25*10=2.5 ≥ 1.0 → satisfiable
        assert (weights >= 0.03 - 1e-9).all()
        assert (weights <= 0.25 + 1e-9).all()

    def test_monte_carlo_frontier_returns_valid_result(
        self,
        sample_prices: pd.DataFrame,
    ) -> None:
        symbols = ["SET000", "SET001", "SET002", "SET003", "SET004"]
        returns = sample_prices[symbols].pct_change().dropna()
        config = OptimizerConfig(mc_samples=2_000)
        result = WeightOptimizer().monte_carlo_frontier(symbols, returns, config)
        assert result.n_samples == 2_000
        assert len(result.frontier_returns) == 2_000
        assert len(result.is_efficient) == 2_000
        assert sum(result.is_efficient) >= 1  # at least one efficient point
        assert result.max_sharpe_ratio > 0

    def test_monte_carlo_frontier_max_sharpe_is_best(
        self,
        sample_prices: pd.DataFrame,
    ) -> None:
        """The reported max_sharpe_ratio is >= every Sharpe on the frontier."""
        symbols = ["SET000", "SET001", "SET002", "SET003", "SET004"]
        returns = sample_prices[symbols].pct_change().dropna()
        config = OptimizerConfig(mc_samples=2_000)
        result = WeightOptimizer().monte_carlo_frontier(symbols, returns, config)
        assert result.max_sharpe_ratio == pytest.approx(
            max(result.frontier_sharpes),
            rel=1e-9,
        )

    def test_monte_carlo_frontier_has_equal_weight_benchmark(
        self,
        sample_prices: pd.DataFrame,
    ) -> None:
        symbols = ["SET000", "SET001", "SET002", "SET003", "SET004"]
        returns = sample_prices[symbols].pct_change().dropna()
        config = OptimizerConfig(mc_samples=2_000)
        result = WeightOptimizer().monte_carlo_frontier(symbols, returns, config)
        assert result.equal_weight_return != 0.0
        assert result.equal_weight_volatility > 0.0
        assert isinstance(result.equal_weight_sharpe, float)

    def test_monte_carlo_deterministic_with_seed(
        self,
        sample_prices: pd.DataFrame,
    ) -> None:
        """Same input → same result (fixed seed)."""
        symbols = ["SET000", "SET001", "SET002", "SET003", "SET004"]
        returns = sample_prices[symbols].pct_change().dropna()
        config = OptimizerConfig(mc_samples=2_000)
        r1 = WeightOptimizer().monte_carlo_frontier(symbols, returns, config)
        r2 = WeightOptimizer().monte_carlo_frontier(symbols, returns, config)
        assert r1.max_sharpe_ratio == pytest.approx(r2.max_sharpe_ratio)
        assert r1.max_sharpe_weights == r2.max_sharpe_weights

    def test_monte_carlo_frontier_needs_two_assets(
        self,
        small_prices: pd.DataFrame,
    ) -> None:
        returns = small_prices[["A"]].pct_change().dropna()
        config = OptimizerConfig()
        with pytest.raises(OptimizationError, match="at least 2"):
            WeightOptimizer().monte_carlo_frontier(["A"], returns, config)
