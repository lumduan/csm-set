"""Market regime detection utilities."""

import logging
from enum import StrEnum

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class RegimeState(StrEnum):
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

    @staticmethod
    def compute_ema(prices: pd.Series, window: int) -> pd.Series:
        """Compute exponential moving average with given span.

        Returns an empty Series when the input has fewer than *window* bars
        (min_periods=window ensures NaN-free output beyond the warm-up).
        """
        if len(prices) < window:
            return pd.Series(dtype=float)
        return prices.ewm(span=window, adjust=False, min_periods=window).mean()

    def is_bull_market(
        self,
        index_prices: pd.Series,
        asof: pd.Timestamp,
        window: int = 200,
    ) -> bool:
        """Return True when the last close is above its EMA-*window*.

        Defaults to True (Bull) when history is insufficient — conservative
        assumption that avoids forcing Safe Mode during the warm-up period.
        """
        history: pd.Series = index_prices.loc[index_prices.index <= asof].dropna()
        ema: pd.Series = self.compute_ema(history, window)
        if ema.empty:
            logger.debug(
                "Insufficient history for EMA-%d at %s — defaulting to Bull",
                window,
                asof,
            )
            return True
        return bool(float(history.iloc[-1]) > float(ema.iloc[-1]))

    def has_negative_ema_slope(
        self,
        index_prices: pd.Series,
        asof: pd.Timestamp,
        window: int = 200,
        slope_lookback: int = 21,
    ) -> bool:
        """Return True when EMA-*window* is falling at *asof*.

        Compares EMA at asof vs EMA *slope_lookback* bars earlier.
        Returns False (conservative) when there is insufficient history —
        avoids triggering 100% cash prematurely during warm-up.
        """
        history: pd.Series = index_prices.loc[index_prices.index <= asof].dropna()
        ema: pd.Series = self.compute_ema(history, window)
        if len(ema) < slope_lookback + 1:
            logger.debug(
                "Insufficient EMA history for slope check at %s — defaulting to flat",
                asof,
            )
            return False
        return bool(float(ema.iloc[-1]) < float(ema.iloc[-(slope_lookback + 1)]))


__all__: list[str] = ["RegimeDetector", "RegimeState"]
