"""Price-cleaning utilities for feature and backtest inputs."""

import logging

import numpy as np
import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class PriceCleaner:
    """Clean wide price matrices and compute return series."""

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean a wide price matrix.

        Args:
            df: Wide price DataFrame with symbols as columns.

        Returns:
            Cleaned price DataFrame with the same surviving columns.
        """

        forward_filled: pd.DataFrame = df.ffill(limit=5)
        missing_ratio: pd.Series = forward_filled.isna().mean()
        retained_columns: list[str] = missing_ratio[missing_ratio <= 0.20].index.tolist()
        filtered: pd.DataFrame = forward_filled[retained_columns].copy()
        if filtered.empty:
            return filtered

        log_returns: pd.DataFrame = self.compute_returns(filtered)
        lower: pd.Series = log_returns.quantile(0.01)
        upper: pd.Series = log_returns.quantile(0.99)
        clipped_returns: pd.DataFrame = log_returns.clip(lower=lower, upper=upper, axis=1)

        base_prices: pd.Series = filtered.iloc[0].ffill().bfill()
        reconstructed: pd.DataFrame = pd.DataFrame(index=filtered.index, columns=filtered.columns, dtype=float)
        reconstructed.iloc[0] = base_prices
        for row_number in range(1, len(filtered.index)):
            prior_prices: pd.Series = reconstructed.iloc[row_number - 1]
            next_prices: pd.Series = prior_prices * np.exp(clipped_returns.iloc[row_number - 1])
            reconstructed.iloc[row_number] = next_prices

        reconstructed = reconstructed.ffill()
        logger.info("Cleaned price matrix", extra={"symbols": len(reconstructed.columns)})
        return reconstructed

    def compute_returns(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Compute daily log returns from price data.

        Args:
            prices: Wide price DataFrame.

        Returns:
            Wide DataFrame of daily log returns.
        """

        returns: pd.DataFrame = np.log(prices / prices.shift(1))
        return returns.iloc[1:]


__all__: list[str] = ["PriceCleaner"]