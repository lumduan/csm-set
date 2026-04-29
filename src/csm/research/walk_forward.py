"""Walk-forward (expanding-window) cross-validation for momentum backtests."""

import logging
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, Field

from csm.data.store import ParquetStore
from csm.research.backtest import BacktestConfig, MomentumBacktest
from csm.research.exceptions import BacktestError

logger: logging.Logger = logging.getLogger(__name__)


class WalkForwardConfig(BaseModel):
    """Configuration for an expanding-window walk-forward analysis."""

    n_folds: int = Field(default=5)
    test_years: int = Field(default=1)
    min_train_years: int = Field(default=5)


class WalkForwardFoldResult(BaseModel):
    """Out-of-sample metrics for one walk-forward fold."""

    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    oos_metrics: dict[str, float]


class WalkForwardResult(BaseModel):
    """Aggregated results from a full walk-forward analysis."""

    generated_at: str
    folds: list[WalkForwardFoldResult]
    aggregate_oos_metrics: dict[str, float]
    is_vs_oos_sharpe: float
    is_metrics: dict[str, float]


class WalkForwardAnalyzer:
    """Expanding-window walk-forward cross-validation.

    For each fold i the backtest is run on the OOS test window
    [fold_cutoff_i, fold_cutoff_i + test_years]. The full in-sample run uses
    the entire date range. IS vs OOS Sharpe ratio > 1 indicates overfitting.
    """

    def __init__(self, store: ParquetStore) -> None:
        self._store: ParquetStore = store

    def _split_dates(
        self,
        all_dates: list[pd.Timestamp],
        wf_config: WalkForwardConfig,
    ) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
        """Return (train_end, test_start, test_end) tuples for each fold.

        Raises BacktestError when the date range is too short for even one fold.
        """
        if not all_dates:
            raise BacktestError("No rebalance dates available for walk-forward analysis.")

        start: pd.Timestamp = all_dates[0]
        end: pd.Timestamp = all_dates[-1]
        total_years: float = (end - start).days / 365.25
        min_total: float = wf_config.min_train_years + wf_config.test_years
        if total_years < min_total:
            raise BacktestError(
                f"Walk-forward requires at least {min_total:.1f} years of data "
                f"({wf_config.min_train_years} train + {wf_config.test_years} test); "
                f"only {total_years:.1f} years available."
            )

        folds: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
        test_delta: pd.DateOffset = pd.DateOffset(years=wf_config.test_years)
        train_min_end: pd.Timestamp = start + pd.DateOffset(years=wf_config.min_train_years)

        for i in range(wf_config.n_folds):
            test_start: pd.Timestamp = train_min_end + pd.DateOffset(years=i * wf_config.test_years)
            test_end: pd.Timestamp = test_start + test_delta
            if test_end > end:
                break
            # train_end is the last date strictly before test_start
            train_dates_before: list[pd.Timestamp] = [d for d in all_dates if d < test_start]
            if not train_dates_before:
                break
            train_end: pd.Timestamp = train_dates_before[-1]
            folds.append((train_end, test_start, test_end))

        if not folds:
            raise BacktestError("Walk-forward produced no valid folds. Increase the date range.")
        return folds

    def run(
        self,
        feature_panel: pd.DataFrame,
        prices: pd.DataFrame,
        config: BacktestConfig,
        wf_config: WalkForwardConfig,
        *,
        volumes: pd.DataFrame | None = None,
        index_prices: pd.Series | None = None,
        sector_map: dict[str, str] | None = None,
    ) -> WalkForwardResult:
        """Run expanding-window walk-forward analysis.

        Args:
            feature_panel: Full MultiIndex feature panel (date, symbol).
            prices: Wide close-price matrix.
            config: Backtest configuration applied to every fold and the IS run.
            wf_config: Walk-forward split parameters.
            volumes: Optional volume matrix for ADTV filtering.
            index_prices: Optional SET index close series for regime detection.
            sector_map: Optional symbol → sector mapping for sector cap.

        Returns:
            WalkForwardResult with per-fold OOS metrics and IS vs OOS Sharpe.

        Raises:
            BacktestError: When the date range is insufficient or no folds are produced.
        """
        if feature_panel.empty or prices.empty:
            raise BacktestError("Feature panel and prices are required for walk-forward analysis.")

        all_dates: list[pd.Timestamp] = list(feature_panel.index.get_level_values("date").unique())
        fold_splits: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = self._split_dates(
            all_dates, wf_config
        )

        fold_results: list[WalkForwardFoldResult] = []
        backtest: MomentumBacktest = MomentumBacktest(self._store)

        for fold_idx, (train_end, test_start, test_end) in enumerate(fold_splits):
            logger.info(
                "Walk-forward fold %d/%d: test [%s, %s]",
                fold_idx + 1,
                len(fold_splits),
                test_start.date(),
                test_end.date(),
            )
            # Slice feature panel and prices to the OOS test window.
            oos_dates_mask: list[pd.Timestamp] = [
                d for d in all_dates if test_start <= d <= test_end
            ]
            if len(oos_dates_mask) < 2:
                logger.warning("Fold %d skipped — fewer than 2 OOS dates", fold_idx + 1)
                continue

            # Include one period before test_start so the first OOS period has
            # a prior date to compute turnover and initial holdings.
            train_dates: list[pd.Timestamp] = [d for d in all_dates if d <= train_end]
            anchor_date: pd.Timestamp | None = train_dates[-1] if train_dates else None
            oos_window: list[pd.Timestamp] = (
                [anchor_date] if anchor_date is not None else []
            ) + oos_dates_mask

            try:
                oos_panel: pd.DataFrame = feature_panel.loc[
                    feature_panel.index.get_level_values("date").isin(oos_window)
                ]
                oos_result = backtest.run(
                    oos_panel,
                    prices,
                    config,
                    volumes=volumes,
                    index_prices=index_prices,
                    sector_map=sector_map,
                )
                oos_metrics: dict[str, float] = {k: float(v) for k, v in oos_result.metrics.items()}
            except BacktestError as exc:
                logger.warning("Fold %d backtest failed: %s", fold_idx + 1, exc)
                oos_metrics = {}

            # Find the actual train start from the feature panel
            panel_dates: list[pd.Timestamp] = [d for d in all_dates if d <= train_end]
            train_start_dt: pd.Timestamp = panel_dates[0] if panel_dates else all_dates[0]

            fold_results.append(
                WalkForwardFoldResult(
                    fold=fold_idx + 1,
                    train_start=train_start_dt.strftime("%Y-%m-%d"),
                    train_end=train_end.strftime("%Y-%m-%d"),
                    test_start=test_start.strftime("%Y-%m-%d"),
                    test_end=test_end.strftime("%Y-%m-%d"),
                    oos_metrics=oos_metrics,
                )
            )

        if not fold_results:
            raise BacktestError("Walk-forward analysis produced no fold results.")

        # Aggregate OOS metrics (mean over folds with non-empty metrics).
        valid_folds: list[WalkForwardFoldResult] = [f for f in fold_results if f.oos_metrics]
        aggregate_oos: dict[str, float] = {}
        if valid_folds:
            metric_keys: list[str] = list(valid_folds[0].oos_metrics.keys())
            for key in metric_keys:
                vals: list[float] = [
                    f.oos_metrics[key] for f in valid_folds if key in f.oos_metrics
                ]
                aggregate_oos[key] = float(sum(vals) / len(vals)) if vals else float("nan")

        # Full in-sample run for IS metrics.
        try:
            is_result = backtest.run(
                feature_panel,
                prices,
                config,
                volumes=volumes,
                index_prices=index_prices,
                sector_map=sector_map,
            )
            is_metrics: dict[str, float] = {k: float(v) for k, v in is_result.metrics.items()}
        except BacktestError as exc:
            logger.warning("Full IS backtest failed: %s", exc)
            is_metrics = {}

        is_sharpe: float = float(is_metrics.get("sharpe", float("nan")))
        oos_sharpe: float = float(aggregate_oos.get("sharpe", float("nan")))
        if oos_sharpe != 0.0 and oos_sharpe == oos_sharpe:  # not zero, not NaN
            is_vs_oos_sharpe: float = is_sharpe / oos_sharpe
        else:
            is_vs_oos_sharpe = float("nan")

        return WalkForwardResult(
            generated_at=datetime.now().isoformat(),
            folds=fold_results,
            aggregate_oos_metrics=aggregate_oos,
            is_vs_oos_sharpe=is_vs_oos_sharpe,
            is_metrics=is_metrics,
        )


__all__: list[str] = [
    "WalkForwardAnalyzer",
    "WalkForwardConfig",
    "WalkForwardFoldResult",
    "WalkForwardResult",
]
