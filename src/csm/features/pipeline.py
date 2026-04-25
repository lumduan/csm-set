"""Feature pipeline orchestration for csm-set."""

import logging

import pandas as pd

from csm.data.store import ParquetStore
from csm.features.momentum import MomentumFeatures
from csm.features.risk_adjusted import RiskAdjustedFeatures

logger: logging.Logger = logging.getLogger(__name__)

_INDEX_SYMBOL: str = "SET:SET"


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
            prices: Mapping from symbol to OHLCV DataFrames. If the key ``SET:SET``
                    is present, risk-adjusted features (sharpe_momentum,
                    residual_momentum) are computed for each symbol.
            rebalance_dates: Rebalance timestamps.

        Returns:
            MultiIndex DataFrame with index `(date, symbol)` and normalized features.
        """
        dates_index: pd.DatetimeIndex = pd.DatetimeIndex(rebalance_dates)

        # Extract SET index close if available (needed for risk-adjusted features).
        index_close: pd.Series | None = None
        if _INDEX_SYMBOL in prices:
            index_close = prices[_INDEX_SYMBOL]["close"]

        # Compute momentum and risk-adjusted features once per symbol.
        symbol_momentum: dict[str, pd.DataFrame] = {}
        symbol_risk: dict[str, pd.DataFrame] = {}
        for symbol, frame in prices.items():
            if symbol == _INDEX_SYMBOL:
                continue
            series: pd.Series = frame["close"].rename(symbol)
            try:
                mom_df: pd.DataFrame = self._momentum.compute(series, dates_index)
                symbol_momentum[symbol] = mom_df
            except Exception:
                logger.warning("Skipping momentum for symbol %s", symbol)
            if index_close is not None:
                try:
                    risk_df: pd.DataFrame = self._risk_adjusted.compute(
                        series, index_close, dates_index
                    )
                    symbol_risk[symbol] = risk_df
                except Exception:
                    logger.warning("Skipping risk-adjusted features for symbol %s", symbol)

        panel_frames: list[pd.DataFrame] = []
        for rebalance_date in rebalance_dates:
            # Collect per-symbol features for this date.
            date_rows: list[dict[str, object]] = []
            for symbol, mom_df in symbol_momentum.items():
                if rebalance_date not in mom_df.index:
                    continue
                row: dict[str, object] = {"symbol": symbol}
                row.update(mom_df.loc[rebalance_date].to_dict())
                if symbol in symbol_risk and rebalance_date in symbol_risk[symbol].index:
                    row.update(symbol_risk[symbol].loc[rebalance_date].to_dict())
                date_rows.append(row)

            if not date_rows:
                continue

            feature_frame: pd.DataFrame = pd.DataFrame(date_rows).set_index("symbol")
            feature_cols: list[str] = list(feature_frame.columns)

            # Drop rows with any NaN before z-scoring.
            feature_frame = feature_frame.dropna()
            if feature_frame.empty:
                logger.warning("No valid symbols on %s after NaN drop", rebalance_date)
                continue

            winsorised: pd.DataFrame = feature_frame.copy()
            for column in feature_cols:
                if column not in winsorised.columns:
                    continue
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
