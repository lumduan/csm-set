"""Feature pipeline orchestration for csm-set."""

import logging

import pandas as pd

from csm.data.store import ParquetStore
from csm.features.momentum import MomentumFeatures
from csm.features.risk_adjusted import RiskAdjustedFeatures

logger: logging.Logger = logging.getLogger(__name__)


class FeaturePipeline:
    """Build and persist feature panels used by ranking and backtests."""

    def __init__(self, store: ParquetStore) -> None:
        self._store: ParquetStore = store
        self._momentum: MomentumFeatures = MomentumFeatures()
        self._risk_adjusted: RiskAdjustedFeatures = RiskAdjustedFeatures()

    def build(
        self, prices: dict[str, pd.DataFrame], rebalance_dates: list[pd.Timestamp]
    ) -> pd.DataFrame:
        """Build a z-scored feature panel across rebalance dates.

        Args:
            prices: Mapping from symbol to OHLCV DataFrames.
            rebalance_dates: Rebalance timestamps.

        Returns:
            MultiIndex DataFrame with index `(date, symbol)` and normalized features.
        """

        close_frames: list[pd.Series] = []
        for symbol, frame in prices.items():
            series: pd.Series = frame["close"].rename(symbol)
            close_frames.append(series)
        close_matrix: pd.DataFrame = (
            pd.concat(close_frames, axis=1).sort_index() if close_frames else pd.DataFrame()
        )

        panel_frames: list[pd.DataFrame] = []
        for rebalance_date in rebalance_dates:
            history: pd.DataFrame = close_matrix.loc[close_matrix.index <= rebalance_date]
            if history.empty:
                continue
            try:
                momentum_frame: pd.DataFrame = self._momentum.compute_multi(history)
            except Exception:
                continue
            sharpe_signal: pd.Series = self._risk_adjusted.sharpe_momentum(history)
            feature_frame: pd.DataFrame = momentum_frame.join(sharpe_signal, how="outer")
            winsorised: pd.DataFrame = feature_frame.copy()
            for column in winsorised.columns:
                lower: float = float(winsorised[column].quantile(0.01))
                upper: float = float(winsorised[column].quantile(0.99))
                winsorised[column] = winsorised[column].clip(lower=lower, upper=upper)
                std: float = float(winsorised[column].std(ddof=0))
                mean: float = float(winsorised[column].mean())
                winsorised[column] = 0.0 if std == 0.0 else (winsorised[column] - mean) / std
            winsorised["date"] = rebalance_date
            panel_frames.append(winsorised.reset_index(names="symbol"))

        if not panel_frames:
            empty_index: pd.MultiIndex = pd.MultiIndex.from_arrays(
                [[], []], names=["date", "symbol"]
            )
            return pd.DataFrame(index=empty_index)

        panel: pd.DataFrame = pd.concat(panel_frames, ignore_index=True)
        panel = panel.set_index(["date", "symbol"]).sort_index()
        self._store.save("features_latest", panel.reset_index())
        logger.info("Built feature panel", extra={"rows": len(panel.index)})
        return panel

    def load_latest(self) -> pd.DataFrame:
        """Load the latest persisted feature panel from the store."""

        latest: pd.DataFrame = self._store.load("features_latest")
        latest["date"] = pd.to_datetime(latest["date"])
        return latest.set_index(["date", "symbol"]).sort_index()


__all__: list[str] = ["FeaturePipeline"]
