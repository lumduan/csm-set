"""Portfolio selection and construction utilities."""

import logging

import pandas as pd

from csm.portfolio.exceptions import PortfolioError

logger: logging.Logger = logging.getLogger(__name__)


class PortfolioConstructor:
    """Build portfolio holdings from ranked signals and target weights."""

    def select(self, ranked: pd.DataFrame, top_quantile: float) -> list[str]:
        """Select symbols from the top bucket of the ranked signal table.

        Args:
            ranked: Ranked signal table.
            top_quantile: Fraction of names to select.

        Returns:
            List of selected symbols.
        """

        if ranked.empty:
            return []
        threshold: int = 5 if abs(top_quantile - 0.2) < 1e-9 else int(round((1.0 - top_quantile) * 5 + 1))
        selected: list[str] = ranked.loc[ranked["quintile"] >= threshold, "symbol"].tolist()
        logger.info("Selected portfolio names", extra={"count": len(selected)})
        return selected

    def build(self, selected: list[str], weights: pd.Series, as_of: pd.Timestamp) -> pd.DataFrame:
        """Build a holdings DataFrame from selected names and weights.

        Args:
            selected: Selected symbol list.
            weights: Weight vector indexed by symbol.
            as_of: Rebalance date.

        Returns:
            Holdings DataFrame with symbol, weight, and as_of columns.

        Raises:
            PortfolioError: If weights are invalid.
        """

        if (weights < 0.0).any():
            raise PortfolioError("Portfolio weights must be non-negative.")
        total_weight: float = float(weights.sum())
        if abs(total_weight - 1.0) > 1e-6:
            raise PortfolioError("Portfolio weights must sum to 1.0.")
        holdings: pd.DataFrame = pd.DataFrame(
            {
                "symbol": selected,
                "weight": weights.reindex(selected).fillna(0.0).to_numpy(),
                "as_of": as_of,
            }
        )
        return holdings


__all__: list[str] = ["PortfolioConstructor"]