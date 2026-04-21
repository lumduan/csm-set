"""Risk-adjusted feature computations for csm-set."""

import logging

import numpy as np
import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class RiskAdjustedFeatures:
    """Compute volatility-adjusted and residual momentum signals."""

    def sharpe_momentum(self, prices: pd.DataFrame, window: int = 252) -> pd.Series:
        """Compute annualised return divided by annualised volatility.

        Args:
            prices: Wide price matrix with symbols as columns.
            window: Number of trading days used in the lookback window.

        Returns:
            Series indexed by symbol named `sharpe_mom`.
        """

        trailing_prices: pd.DataFrame = prices.tail(window + 1)
        returns: pd.DataFrame = trailing_prices.pct_change().dropna(how="all")
        annual_return: pd.Series = (1.0 + returns.mean()) ** 252 - 1.0
        annual_volatility: pd.Series = returns.std(ddof=0) * np.sqrt(252.0)
        sharpe: pd.Series = annual_return.div(annual_volatility.replace(0.0, np.nan))
        sharpe = sharpe.fillna(0.0)
        sharpe.name = "sharpe_mom"
        logger.info("Computed sharpe momentum", extra={"window": window})
        return sharpe

    def residual_momentum(self, prices: pd.DataFrame, index_prices: pd.Series) -> pd.Series:
        """Compute residual momentum relative to the market index.

        Args:
            prices: Wide price matrix with symbols as columns.
            index_prices: Market index price series.

        Returns:
            Series indexed by symbol named `residual_mom`.
        """

        symbol_returns: pd.DataFrame = prices.pct_change().dropna(how="all").tail(252)
        market_returns: pd.Series = (
            index_prices.pct_change().dropna().reindex(symbol_returns.index).fillna(0.0)
        )
        residual_scores: dict[str, float] = {}
        variance: float = float(market_returns.var(ddof=0))

        for symbol in symbol_returns.columns:
            aligned: pd.Series = symbol_returns[symbol].fillna(0.0)
            if variance == 0.0:
                residual_scores[symbol] = float(aligned.sum())
                continue
            covariance: float = float(
                np.cov(aligned.to_numpy(), market_returns.to_numpy(), ddof=0)[0, 1]
            )
            beta: float = covariance / variance
            alpha: float = float(aligned.mean() - beta * market_returns.mean())
            residuals: pd.Series = aligned - (alpha + beta * market_returns)
            residual_scores[symbol] = float(residuals.sum())

        residual_momentum: pd.Series = pd.Series(residual_scores, name="residual_mom", dtype=float)
        logger.info("Computed residual momentum", extra={"symbols": len(residual_momentum.index)})
        return residual_momentum


__all__: list[str] = ["RiskAdjustedFeatures"]
