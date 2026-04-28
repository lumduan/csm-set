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
    EARLY_BULL = "EARLY_BULL"  # SET < EMA-200 but market breadth recovering (Phase 3.7)


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

    @staticmethod
    def compute_market_breadth(
        prices: pd.DataFrame,
        asof: pd.Timestamp,
        ema_window: int = 20,
    ) -> float:
        """Return the fraction of stocks trading above their EMA-*ema_window* at *asof*.

        Uses the full *prices* matrix as a proxy for SET100 breadth. Returns 0.5
        (neutral) when there is insufficient history to compute the EMA, avoiding
        false signals during the warm-up period.

        Args:
            prices: Wide close-price DataFrame (date rows × symbol columns).
            asof: Evaluation date — only data up to this date is used.
            ema_window: Exponential moving average window in trading days.

        Returns:
            Fraction in [0.0, 1.0]; 0.5 when history is insufficient.
        """
        history: pd.DataFrame = prices.loc[:asof].dropna()
        if len(history) < ema_window + 5:
            return 0.5
        ema: pd.DataFrame = history.ewm(
            span=ema_window, adjust=False, min_periods=ema_window
        ).mean()
        above: int = int((history.iloc[-1] > ema.iloc[-1]).sum())
        total: int = len(history.columns)
        return float(above / total) if total > 0 else 0.5


__all__: list[str] = ["RegimeDetector", "RegimeState"]
