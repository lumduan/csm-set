"""Market regime detection utilities."""

from enum import Enum
import logging

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class RegimeState(str, Enum):
    """Discrete market regime states."""

    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"


class RegimeDetector:
    """Detect broad market regimes from index price action."""

    def detect(self, index_prices: pd.Series, as_of: pd.Timestamp) -> RegimeState:
        """Detect the current market regime from index prices."""

        history: pd.Series = index_prices.loc[index_prices.index <= as_of].dropna()
        if len(history.index) < 200:
            return RegimeState.NEUTRAL
        price: float = float(history.iloc[-1])
        sma_200: float = float(history.tail(200).mean())
        trailing_return: float = float((history.iloc[-1] / history.iloc[-63]) - 1.0)
        if price > sma_200 and trailing_return > 0.0:
            return RegimeState.BULL
        if price < sma_200 and trailing_return < -0.05:
            return RegimeState.BEAR
        return RegimeState.NEUTRAL

    def position_scale(self, regime: RegimeState) -> float:
        """Map a detected regime to a portfolio exposure scalar."""

        if regime is RegimeState.BULL:
            return 1.0
        if regime is RegimeState.BEAR:
            return 0.5
        return 0.75


__all__: list[str] = ["RegimeDetector", "RegimeState"]