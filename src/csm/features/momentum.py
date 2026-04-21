"""Cross-sectional momentum feature computation."""

import logging

import pandas as pd

from csm.config.constants import REBALANCE_FREQUENCY
from csm.features.exceptions import InsufficientDataError

logger: logging.Logger = logging.getLogger(__name__)


class MomentumFeatures:
    """Compute momentum signals from wide price matrices."""

    def compute(
        self,
        prices: pd.DataFrame,
        formation_months: int,
        skip_months: int,
    ) -> pd.Series:
        """Compute a momentum snapshot for one lookback definition.

        Args:
            prices: Wide price matrix with symbols as columns.
            formation_months: Number of formation months.
            skip_months: Number of skip months before the rebalance date.

        Returns:
            Series indexed by symbol containing trailing momentum returns.

        Raises:
            InsufficientDataError: If insufficient monthly history is available.
        """

        monthly_prices: pd.DataFrame = prices.resample(REBALANCE_FREQUENCY).last().dropna(how="all")
        required_rows: int = formation_months + skip_months + 1
        if len(monthly_prices.index) < required_rows:
            raise InsufficientDataError(
                f"Need at least {required_rows} monthly observations, got {len(monthly_prices.index)}."
            )

        end_offset: int = skip_months + 1
        start_offset: int = formation_months + skip_months + 1
        end_prices: pd.Series = monthly_prices.iloc[-end_offset]
        start_prices: pd.Series = monthly_prices.iloc[-start_offset]
        signal: pd.Series = (end_prices / start_prices) - 1.0
        signal.name = f"mom_{formation_months}_{skip_months}"
        logger.info("Computed momentum feature", extra={"name": signal.name})
        return signal

    def compute_multi(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Compute the standard set of momentum features.

        Args:
            prices: Wide price matrix with symbols as columns.

        Returns:
            DataFrame containing 12-1, 6-1, and 3-1 momentum features.
        """

        features: list[pd.Series] = [
            self.compute(prices, formation_months=12, skip_months=1),
            self.compute(prices, formation_months=6, skip_months=1),
            self.compute(prices, formation_months=3, skip_months=1),
        ]
        return pd.concat(features, axis=1)


__all__: list[str] = ["MomentumFeatures"]