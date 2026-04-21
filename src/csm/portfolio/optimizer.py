"""Weight optimization methods for csm-set portfolios."""

import logging

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from csm.portfolio.exceptions import OptimizationError

logger: logging.Logger = logging.getLogger(__name__)


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


__all__: list[str] = ["WeightOptimizer"]
