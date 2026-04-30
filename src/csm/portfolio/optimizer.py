"""Weight optimization methods for csm-set portfolios."""

import logging
from enum import StrEnum

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.optimize import minimize

from csm.portfolio.exceptions import OptimizationError

logger: logging.Logger = logging.getLogger(__name__)


class WeightScheme(StrEnum):
    """Supported weight-allocation schemes."""

    EQUAL = "equal"
    INVERSE_VOL = "inverse_vol"
    VOL_TARGET = "vol_target"
    MIN_VARIANCE = "min_variance"
    MAX_SHARPE = "max_sharpe"


class OptimizerConfig(BaseModel):
    """Configuration for the WeightOptimizer.compute() method."""

    min_position: float = Field(default=0.05, ge=0.0, le=1.0)
    max_position: float = Field(default=0.15, ge=0.0, le=1.0)
    max_holdings: int | None = Field(
        default=None,
        ge=1,
        description="Maximum number of holdings (None = no limit)",
    )
    vol_lookback_days: int = Field(default=63, ge=21, le=504)
    target_position_vol: float = Field(default=0.15, ge=0.0, le=1.0)
    solver_max_iter: int = Field(default=1000, ge=100, le=10000)
    mc_samples: int = Field(default=100_000, ge=1_000, le=1_000_000)
    mc_risk_free_rate: float = Field(default=0.02, ge=0.0, le=0.5)


class MonteCarloResult(BaseModel):
    """Result of a Monte Carlo efficient-frontier simulation."""

    max_sharpe_weights: dict[str, float]
    max_sharpe_return: float
    max_sharpe_volatility: float
    max_sharpe_ratio: float
    frontier_returns: list[float]
    frontier_volatilities: list[float]
    frontier_sharpes: list[float]
    is_efficient: list[bool]
    equal_weight_return: float
    equal_weight_volatility: float
    equal_weight_sharpe: float
    n_samples: int


class WeightOptimizer:
    """Construct portfolio weights using several allocation schemes."""

    def equal_weight(self, symbols: list[str]) -> pd.Series:
        """Assign equal weights to all selected symbols."""

        if not symbols:
            return pd.Series(dtype=float)
        weight: float = 1.0 / len(symbols)
        return pd.Series(weight, index=symbols, dtype=float)

    def vol_target_weight(
        self,
        symbols: list[str],
        returns: pd.DataFrame,
        target_vol: float = 0.15,
    ) -> pd.Series:
        """Compute inverse-volatility weights for a symbol list."""

        if not symbols:
            return pd.Series(dtype=float)
        volatility: pd.Series = returns[symbols].std(ddof=0).replace(0.0, np.nan)
        inverse_volatility: pd.Series = (
            (1.0 / volatility).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        )
        weights: pd.Series = inverse_volatility / inverse_volatility.sum()
        portfolio_volatility: float = float(
            np.sqrt(weights.T @ returns[symbols].cov().fillna(0.0).to_numpy() @ weights)
        )
        logger.info(
            "Computed vol-target weights",
            extra={"target_vol": target_vol, "estimated_vol": portfolio_volatility},
        )
        return weights.fillna(0.0)

    def min_variance_weight(self, symbols: list[str], returns: pd.DataFrame) -> pd.Series:
        """Solve a long-only minimum-variance portfolio.

        Args:
            symbols: Symbols to include.
            returns: Return matrix with symbols as columns.

        Returns:
            Weight series indexed by symbol.

        Raises:
            OptimizationError: If optimization fails.
        """

        if not symbols:
            return pd.Series(dtype=float)
        covariance: np.ndarray = returns[symbols].cov().fillna(0.0).to_numpy()
        initial_weights: np.ndarray = np.full(len(symbols), 1.0 / len(symbols), dtype=float)

        def objective(weight_vector: np.ndarray) -> float:
            return float(weight_vector.T @ covariance @ weight_vector)

        constraints: tuple[dict[str, object], ...] = (
            {"type": "eq", "fun": lambda values: float(np.sum(values) - 1.0)},
        )
        bounds: tuple[tuple[float, float], ...] = tuple((0.0, 1.0) for _ in symbols)
        result = minimize(objective, initial_weights, bounds=bounds, constraints=constraints)
        if not result.success:
            raise OptimizationError(f"Minimum-variance optimization failed: {result.message}")
        return pd.Series(result.x, index=symbols, dtype=float)

    def _inverse_vol_weights(
        self, symbols: list[str], returns: pd.DataFrame
    ) -> pd.Series:
        """Compute inverse-volatility weights (no target-vol logging)."""
        if not symbols:
            return pd.Series(dtype=float)
        volatility: pd.Series = returns[symbols].std(ddof=0).replace(0.0, np.nan)
        inverse_volatility: pd.Series = (
            (1.0 / volatility).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        )
        weights: pd.Series = inverse_volatility / inverse_volatility.sum()
        return weights.fillna(0.0)

    def _enforce_position_constraints(
        self, weights: pd.Series, config: OptimizerConfig,
    ) -> pd.Series:
        """Clip each weight to [min_position, max_position] and renormalise to sum 1.0.

        Applies cap enforcement first (top-down redistribution of excess), then
        floor enforcement (bottom-up funding of deficit). Iterates up to 10
        rounds since a floor lift can push a previously-safe weight above the cap.
        Falls back to equal weight when constraints are unsatisfiable.
        """
        if weights.empty:
            return weights
        n: int = len(weights)
        if n * config.max_position < 1.0 - 1e-12:
            logger.warning(
                "Position cap unsatisfiable (n=%d, max=%.4f); falling back to equal weight",
                n, config.max_position,
            )
            return pd.Series(1.0 / n, index=weights.index, dtype=float)
        if n * config.min_position > 1.0 + 1e-12:
            logger.warning(
                "Position floor unsatisfiable (n=%d, min=%.4f); falling back to equal weight",
                n, config.min_position,
            )
            return pd.Series(1.0 / n, index=weights.index, dtype=float)

        w: pd.Series = weights.copy()
        for _ in range(10):
            # Enforce cap: clip overweights down, redistribute excess to free weights
            above: pd.Series = w > config.max_position
            if above.any():
                excess: float = float((w[above] - config.max_position).sum())
                w[above] = config.max_position
                free: pd.Series = ~above
                if free.any():
                    w[free] += excess / float(free.sum())
            # Enforce floor: lift underweights up, fund deficit from free weights
            below: pd.Series = w < config.min_position
            if below.any():
                deficit: float = float((config.min_position - w[below]).sum())
                w[below] = config.min_position
                free = ~below
                if free.any():
                    w[free] -= deficit / float(free.sum())
            if not (w > config.max_position + 1e-9).any() and not (
                w < config.min_position - 1e-9
            ).any():
                break
        else:
            logger.warning(
                "Position constraints did not converge (n=%d); falling back to equal weight",
                n,
            )
            return pd.Series(1.0 / n, index=weights.index, dtype=float)
        return w

    def _monte_carlo_optimize(
        self,
        symbols: list[str],
        returns: pd.DataFrame,
        config: OptimizerConfig,
    ) -> pd.Series:
        """Run a vectorised Monte Carlo search for the max-Sharpe weight vector.

        Generates ``config.mc_samples`` Dirichlet-distributed random weight vectors
        in a single batch, computes annualised return, volatility, and Sharpe for
        each, and returns the weights with the highest Sharpe ratio.

        Raises:
            OptimizationError: If the returns matrix is empty or all-NaN.
        """
        n_assets: int = len(symbols)
        return_matrix: np.ndarray = returns[symbols].dropna().to_numpy()
        if return_matrix.shape[0] < 21:
            raise OptimizationError(
                "Insufficient return history for Monte Carlo optimisation"
            )
        rng: np.random.Generator = np.random.default_rng(42)
        # Generate all weight vectors in one batch via Dirichlet(1, …, 1)
        # Shape: (mc_samples, n_assets) — each row sums to 1, all ≥ 0
        weights_matrix: np.ndarray = rng.dirichlet(
            np.ones(n_assets, dtype=float), size=config.mc_samples,
        )
        # Vectorised portfolio metrics
        port_returns: np.ndarray = weights_matrix @ return_matrix.mean(axis=0) * 252
        cov: np.ndarray = np.cov(return_matrix, rowvar=False)
        port_vols: np.ndarray = (
            np.sqrt(np.einsum("ij,jk,ik->i", weights_matrix, cov, weights_matrix))
            * np.sqrt(252)
        )
        # Guard against zero / negative vol
        port_vols = np.maximum(port_vols, 1e-12)
        sharpes: np.ndarray = (
            port_returns - config.mc_risk_free_rate
        ) / port_vols
        best_idx: int = int(np.argmax(sharpes))
        best_weights: np.ndarray = weights_matrix[best_idx].copy()
        # Ensure no negative due to floating-point rounding
        best_weights = np.maximum(best_weights, 0.0)
        best_weights /= best_weights.sum()
        return pd.Series(best_weights, index=symbols, dtype=float)

    def monte_carlo_frontier(
        self,
        symbols: list[str],
        returns: pd.DataFrame,
        config: OptimizerConfig,
    ) -> MonteCarloResult:
        """Run a Monte Carlo simulation and return the efficient frontier.

        Generates random long-only weight vectors, computes annualised return and
        volatility for each, identifies the efficient frontier, and locates the
        portfolio with the maximum Sharpe ratio.

        Args:
            symbols: Symbols to include.
            returns: Return matrix (wide-form DataFrame, symbols as columns).
            config: OptimizerConfig with Monte Carlo parameters.

        Returns:
            MonteCarloResult with frontier data and max-Sharpe portfolio details.
        """
        n_assets: int = len(symbols)
        if n_assets < 2:
            raise OptimizationError("Need at least 2 assets for Monte Carlo frontier")
        return_matrix: np.ndarray = returns[symbols].dropna().to_numpy()
        if return_matrix.shape[0] < 21:
            raise OptimizationError(
                "Insufficient return history for Monte Carlo simulation"
            )
        rng: np.random.Generator = np.random.default_rng(42)
        weights_matrix = rng.dirichlet(
            np.ones(n_assets, dtype=float), size=config.mc_samples,
        )
        # Vectorised portfolio metrics
        mean_ret: np.ndarray = return_matrix.mean(axis=0)
        cov_matrix: np.ndarray = np.cov(return_matrix, rowvar=False)
        annual_factor: float = 252.0
        port_returns: np.ndarray = weights_matrix @ mean_ret * annual_factor
        port_vols: np.ndarray = (
            np.sqrt(
                np.einsum("ij,jk,ik->i", weights_matrix, cov_matrix, weights_matrix)
            )
            * np.sqrt(annual_factor)
        )
        port_vols = np.maximum(port_vols, 1e-12)
        sharpes: np.ndarray = (
            port_returns - config.mc_risk_free_rate
        ) / port_vols

        # Identify efficient frontier (Pareto-optimal points)
        idx_sorted: np.ndarray = np.argsort(port_vols)
        rets_sorted: np.ndarray = port_returns[idx_sorted]
        is_efficient: list[bool] = [False] * config.mc_samples
        max_ret_so_far: float = -np.inf
        efficient_indices: list[int] = []
        for i in range(config.mc_samples):
            orig_idx: int = int(idx_sorted[i])
            if rets_sorted[i] > max_ret_so_far:
                max_ret_so_far = float(rets_sorted[i])
                is_efficient[orig_idx] = True
                efficient_indices.append(orig_idx)

        best_idx: int = int(np.argmax(sharpes))
        best_weights: np.ndarray = np.maximum(weights_matrix[best_idx], 0.0)
        best_weights /= best_weights.sum()

        # Equal-weight benchmark
        ew: np.ndarray = np.full(n_assets, 1.0 / n_assets, dtype=float)
        ew_ret: float = float(ew @ mean_ret * annual_factor)
        ew_vol: float = float(np.sqrt(ew @ cov_matrix @ ew) * np.sqrt(annual_factor))
        ew_sharpe: float = (ew_ret - config.mc_risk_free_rate) / max(ew_vol, 1e-12)

        return MonteCarloResult(
            max_sharpe_weights=dict(zip(symbols, best_weights, strict=True)),
            max_sharpe_return=float(port_returns[best_idx]),
            max_sharpe_volatility=float(port_vols[best_idx]),
            max_sharpe_ratio=float(sharpes[best_idx]),
            frontier_returns=[float(port_returns[i]) for i in range(config.mc_samples)],
            frontier_volatilities=[float(port_vols[i]) for i in range(config.mc_samples)],
            frontier_sharpes=[float(sharpes[i]) for i in range(config.mc_samples)],
            is_efficient=is_efficient,
            equal_weight_return=ew_ret,
            equal_weight_volatility=ew_vol,
            equal_weight_sharpe=ew_sharpe,
            n_samples=config.mc_samples,
        )

    def compute(
        self,
        symbols: list[str],
        prices: pd.DataFrame,
        scheme: WeightScheme,
        config: OptimizerConfig,
    ) -> pd.Series:
        """Compute portfolio weights using the specified scheme.

        Args:
            symbols: Selected symbols to allocate among.
            prices: Wide-form close-price DataFrame indexed by date, columns = symbols.
            scheme: Allocation scheme (EQUAL, INVERSE_VOL, VOL_TARGET, MIN_VARIANCE).
            config: Configuration including position bounds, lookback, and solver settings.

        Returns:
            Weight series indexed by symbol, summing to 1.0, with each element
            in [min_position, max_position] (after enforcement).

        Raises:
            OptimizationError: If a negative weight is produced (indicates a code bug).
        """
        if not symbols:
            return pd.Series(dtype=float)

        # Enforce max_holdings: select top N by trailing total return
        selected: list[str] = list(symbols)
        if config.max_holdings is not None and len(selected) > config.max_holdings:
            trailing_prices: pd.DataFrame = prices[selected]
            if len(trailing_prices) >= 63:
                total_ret = trailing_prices.iloc[-1] / trailing_prices.iloc[0] - 1.0
                ranked = total_ret.sort_values(ascending=False)
                selected = list(ranked.iloc[: config.max_holdings].index)
            else:
                selected = selected[: config.max_holdings]

        trailing_returns: pd.DataFrame = (
            prices[selected].pct_change().dropna(how="all").tail(config.vol_lookback_days)
        )

        if scheme is WeightScheme.EQUAL:
            raw: pd.Series = self.equal_weight(selected)
        elif scheme is WeightScheme.INVERSE_VOL:
            raw = self._inverse_vol_weights(selected, trailing_returns)
        elif scheme is WeightScheme.VOL_TARGET:
            raw = self.vol_target_weight(
                selected, trailing_returns, target_vol=config.target_position_vol,
            )
        elif scheme is WeightScheme.MIN_VARIANCE:
            try:
                raw = self.min_variance_weight(selected, trailing_returns)
            except Exception:
                logger.warning(
                    "Min-variance solver failed; falling back to inverse-vol",
                    exc_info=True,
                )
                raw = self._inverse_vol_weights(selected, trailing_returns)
        elif scheme is WeightScheme.MAX_SHARPE:
            try:
                raw = self._monte_carlo_optimize(selected, trailing_returns, config)
            except Exception:
                logger.warning(
                    "Monte Carlo max-Sharpe failed; falling back to inverse-vol",
                    exc_info=True,
                )
                raw = self._inverse_vol_weights(selected, trailing_returns)
        else:
            raise ValueError(f"Unknown weight scheme: {scheme}")

        if (raw < 0.0).any():
            offending: list[str] = [str(s) for s in raw.index[raw < 0]]
            raise OptimizationError(
                f"Negative weight produced for symbols: {offending}"
            )

        constrained: pd.Series = self._enforce_position_constraints(raw, config)
        return constrained


__all__: list[str] = ["MonteCarloResult", "OptimizerConfig", "WeightOptimizer", "WeightScheme"]
