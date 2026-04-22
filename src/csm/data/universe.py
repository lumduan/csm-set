"""Universe construction utilities for csm-set."""

import logging

import pandas as pd

from csm.config.constants import MIN_AVG_DAILY_VOLUME, MIN_DATA_COVERAGE, MIN_PRICE_THB
from csm.data.exceptions import UniverseError

logger: logging.Logger = logging.getLogger(__name__)


class UniverseBuilder:
    """Build a tradable stock universe from OHLCV inputs."""

    def build(self, price_data: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> list[str]:
        """Apply sequential price, liquidity, and coverage filters.

        Args:
            price_data: Mapping from symbol to OHLCV DataFrame.
            as_of: Universe construction date.

        Returns:
            Sorted list of eligible symbols.

        Raises:
            UniverseError: If no symbols survive the filters.
        """

        selected: list[str] = []
        for symbol, frame in price_data.items():
            history: pd.DataFrame = frame.loc[frame.index <= as_of]
            if history.empty:
                continue
            close_series = history["close"]
            volume_series = history["volume"]
            last_close: float = (
                float(close_series.dropna().iloc[-1]) if close_series.notna().any() else 0.0
            )
            mean_volume: float = (
                float(volume_series.dropna().mean()) if volume_series.notna().any() else 0.0
            )
            coverage: float = float(history["close"].notna().sum() / len(history))

            if last_close < MIN_PRICE_THB:
                continue
            if mean_volume < MIN_AVG_DAILY_VOLUME:
                continue
            if coverage < MIN_DATA_COVERAGE:
                continue
            selected.append(symbol)

        universe: list[str] = sorted(selected)
        if not universe:
            raise UniverseError("Universe construction produced no eligible symbols.")

        logger.info("Built universe", extra={"as_of": str(as_of), "count": len(universe)})
        return universe


__all__: list[str] = ["UniverseBuilder"]
