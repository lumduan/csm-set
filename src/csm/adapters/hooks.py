"""Pipeline event hooks that fan-out write-back to the configured adapters.

Each hook function wraps every adapter write in an independent
``try/except Exception`` block — a single adapter failure is logged at
WARNING and never blocks other adapters or propagates to the pipeline
caller. The master ``db_write_enabled`` flag and per-DSN guards are
handled by ``AdapterManager.from_settings`` upstream, so hook functions
only need to null-check each slot before calling.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from csm.research.ranking import CrossSectionalRanker
from csm.risk.metrics import PerformanceMetrics

if TYPE_CHECKING:
    from csm.adapters import AdapterManager
    from csm.data.store import ParquetStore
    from csm.research.backtest import BacktestConfig, BacktestResult

logger: logging.Logger = logging.getLogger(__name__)
DEFAULT_STRATEGY_ID: str = "csm-set"


async def run_post_refresh_hook(
    manager: AdapterManager,
    store: ParquetStore,
    summary: dict[str, Any] | None = None,
) -> None:
    """Write equity curve, signal snapshot, daily performance, and portfolio
    snapshot after a successful daily refresh.

    Each adapter write is independently ``try/except``-wrapped so a
    Postgres outage does not block Mongo or Gateway writes.

    Args:
        manager: The shared ``AdapterManager`` (each slot may be ``None``).
        store: ``ParquetStore`` from which ``prices_latest`` and
            ``features_latest`` are loaded.
        summary: Optional dict from the refresh run with keys
            ``symbols_fetched``, ``failures``, ``duration_seconds``.
    """
    strategy_id: str = DEFAULT_STRATEGY_ID
    today: datetime = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    # ---------------------------------------------------------------
    # 1. Equity curve → Postgres db_csm_set.equity_curve
    #    Synthetic equal-weight universe NAV computed from prices_latest.
    # ---------------------------------------------------------------
    equity_series: pd.Series | None = None
    metrics: dict[str, float] = {}

    if manager.postgres is not None or manager.gateway is not None:
        try:
            prices: pd.DataFrame = store.load("prices_latest")
        except Exception:
            logger.warning("post-refresh hook: failed to load prices_latest", exc_info=True)
            prices = pd.DataFrame()

        if not prices.empty and len(prices.columns) > 0 and len(prices) > 1:
            daily_returns: pd.Series = prices.pct_change().mean(axis=1).dropna()
            if not daily_returns.empty:
                equity_series = (1.0 + daily_returns).cumprod() * 100.0
                if equity_series.index.tz is None:
                    equity_series.index = equity_series.index.tz_localize("UTC")
                elif str(equity_series.index.tz) != "UTC":
                    equity_series.index = equity_series.index.tz_convert("UTC")

    if manager.postgres is not None and equity_series is not None:
        try:
            await manager.postgres.write_equity_curve(strategy_id, equity_series)
        except Exception:
            logger.warning("post-refresh hook: write_equity_curve failed", exc_info=True)

    # ---------------------------------------------------------------
    # 2. Signal snapshot → Mongo csm_logs.signal_snapshots
    #    Rank all numeric features cross-sectionally for the latest date.
    # ---------------------------------------------------------------
    if manager.mongo is not None:
        try:
            feature_panel: pd.DataFrame = store.load("features_latest")
            if not feature_panel.empty and "date" in feature_panel.columns:
                feature_panel = feature_panel.copy()
                feature_panel["date"] = pd.to_datetime(feature_panel["date"])
                feature_panel = feature_panel.set_index(["date", "symbol"]).sort_index()
                latest_date = feature_panel.index.get_level_values("date").max()
                ranking_df: pd.DataFrame = CrossSectionalRanker().rank_all(feature_panel)
                latest_ranking: pd.DataFrame = ranking_df.xs(latest_date, level="date")
                rankings_list: list[dict[str, object]] = []
                for symbol_idx, row in latest_ranking.iterrows():
                    entry: dict[str, object] = {"symbol": str(symbol_idx)}
                    for col, val in row.items():
                        if isinstance(val, (np.floating, float)):
                            if not np.isnan(val):
                                entry[col] = float(val)
                        elif val is not None and not (isinstance(val, float) and np.isnan(val)):
                            entry[col] = val
                    rankings_list.append(entry)
                snapshot_ts = pd.Timestamp(latest_date)
                if snapshot_ts.tz is None:
                    snapshot_ts = snapshot_ts.tz_localize("UTC")
                elif str(snapshot_ts.tz) != "UTC":
                    snapshot_ts = snapshot_ts.tz_convert("UTC")
                snapshot_date: datetime = snapshot_ts.to_pydatetime()
                await manager.mongo.write_signal_snapshot(strategy_id, snapshot_date, rankings_list)
        except Exception:
            logger.warning("post-refresh hook: write_signal_snapshot failed", exc_info=True)

    # ---------------------------------------------------------------
    # 3. Compute performance metrics → shared by daily_performance and
    #    portfolio_snapshot Gateway writes below.
    # ---------------------------------------------------------------
    if equity_series is not None and len(equity_series) > 1:
        try:
            pm = PerformanceMetrics()
            metrics = pm.summary(equity_series)
        except Exception:
            logger.warning("post-refresh hook: PerformanceMetrics.summary failed", exc_info=True)

    # ---------------------------------------------------------------
    # 4. Daily performance → Gateway db_gateway.daily_performance
    # ---------------------------------------------------------------
    if manager.gateway is not None:
        try:
            latest_nav: float = (
                float(equity_series.iloc[-1])
                if equity_series is not None and not equity_series.empty
                else 100.0
            )
            daily_return: float = (
                float(equity_series.pct_change().iloc[-1])
                if equity_series is not None and len(equity_series) > 1
                else 0.0
            )
            cumulative_return: float = latest_nav / 100.0 - 1.0
            gateway_metrics: dict[str, object] = {
                "daily_return": daily_return,
                "cumulative_return": cumulative_return,
                "total_value": latest_nav,
                "cash_balance": 0.0,
                "max_drawdown": metrics.get("max_drawdown", 0.0),
                "sharpe_ratio": metrics.get("sharpe", 0.0),
                "symbols_fetched": (summary or {}).get("symbols_fetched", 0),
                "failures": (summary or {}).get("failures", 0),
                "duration_seconds": (summary or {}).get("duration_seconds", 0.0),
            }
            await manager.gateway.write_daily_performance(strategy_id, today, gateway_metrics)
        except Exception:
            logger.warning("post-refresh hook: write_daily_performance failed", exc_info=True)

    # ---------------------------------------------------------------
    # 5. Portfolio snapshot → Gateway db_gateway.portfolio_snapshot
    # ---------------------------------------------------------------
    if manager.gateway is not None:
        try:
            latest_nav_val: float = (
                float(equity_series.iloc[-1])
                if equity_series is not None and not equity_series.empty
                else 100.0
            )
            snapshot: dict[str, object] = {
                "total_portfolio": latest_nav_val,
                "weighted_return": (summary or {}).get("weighted_return", 0.0),
                "combined_drawdown": metrics.get("max_drawdown", 0.0),
                "active_strategies": 1,
                "allocation": {strategy_id: 1.0},
            }
            await manager.gateway.write_portfolio_snapshot(today, snapshot)
        except Exception:
            logger.warning("post-refresh hook: write_portfolio_snapshot failed", exc_info=True)


async def run_post_backtest_hook(
    manager: AdapterManager,
    run_id: str,
    strategy_id: str,
    config: BacktestConfig,
    result: BacktestResult,
) -> None:
    """Write backtest log, result document, and model params after a
    successful backtest run.

    Each adapter write is independently ``try/except``-wrapped so a
    Postgres outage does not block Mongo writes and vice versa.

    Args:
        manager: The shared ``AdapterManager`` (each slot may be ``None``).
        run_id: Unique identifier for this backtest run.
        strategy_id: Strategy identifier (e.g. ``"csm-set"``).
        config: The ``BacktestConfig`` used for the run.
        result: The full ``BacktestResult`` object.
    """
    config_dict: dict[str, object] = config.model_dump()
    metrics_dict_all: dict[str, object] = result.metrics_dict()

    # ---------------------------------------------------------------
    # 1. Backtest log → Postgres db_csm_set.backtest_log
    # ---------------------------------------------------------------
    if manager.postgres is not None:
        try:
            await manager.postgres.write_backtest_log(
                run_id=run_id,
                strategy_id=strategy_id,
                config=config_dict,
                summary=metrics_dict_all,
            )
        except Exception:
            logger.warning("post-backtest hook: write_backtest_log failed", exc_info=True)

    # ---------------------------------------------------------------
    # 2. Backtest result → Mongo csm_logs.backtest_results
    #    Full document with equity curve, positions, turnover, trades.
    # ---------------------------------------------------------------
    if manager.mongo is not None:
        try:
            trades_list: list[dict[str, object]] = []
            for period in result.monthly_report.periods:
                for holding in period.holdings:
                    trades_list.append(
                        {
                            "period_end": period.period_end,
                            "symbol": holding.symbol,
                            "weight": holding.weight,
                            "return_pct": holding.return_pct,
                        }
                    )
            result_doc: dict[str, object] = {
                "run_id": run_id,
                "strategy_id": strategy_id,
                "created_at": datetime.now(tz=UTC),
                "config": config_dict,
                "metrics": result.metrics,
                "equity_curve": result.equity_curve,
                "positions": result.positions,
                "turnover": result.turnover,
                "annual_returns": result.annual_returns,
                "trades": trades_list,
            }
            await manager.mongo.write_backtest_result(result_doc)
        except Exception:
            logger.warning("post-backtest hook: write_backtest_result failed", exc_info=True)

    # ---------------------------------------------------------------
    # 3. Model params → Mongo csm_logs.model_params
    # ---------------------------------------------------------------
    if manager.mongo is not None:
        try:
            version: str = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
            await manager.mongo.write_model_params(strategy_id, version, config_dict)
        except Exception:
            logger.warning("post-backtest hook: write_model_params failed", exc_info=True)


async def run_post_rebalance_hook(
    manager: AdapterManager,
    strategy_id: str,
    trades: pd.DataFrame,
) -> None:
    """Write trade history after a rebalance event.

    Each adapter write is independently ``try/except``-wrapped.

    Args:
        manager: The shared ``AdapterManager`` (each slot may be ``None``).
        strategy_id: Strategy identifier.
        trades: DataFrame with columns ``time``, ``symbol``, ``side``,
            ``quantity``, ``price``, ``commission``. All timestamps must
            be tz-aware UTC.
    """
    if manager.postgres is not None:
        try:
            await manager.postgres.write_trade_history(strategy_id, trades)
        except Exception:
            logger.warning("post-rebalance hook: write_trade_history failed", exc_info=True)


__all__: list[str] = [
    "run_post_backtest_hook",
    "run_post_rebalance_hook",
    "run_post_refresh_hook",
]
