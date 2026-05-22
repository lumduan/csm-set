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
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from csm.adapters.gateway_client import GatewayWriteError
from csm.adapters.payload import DEFAULT_STRATEGY_TYPE, build_ingestion_payload
from csm.config.settings import Settings, get_settings
from csm.data.benchmark import BenchmarkLoader
from csm.data.exceptions import BenchmarkUnavailableError
from csm.execution.trade_pairing import ClosedTrade
from csm.live import (
    LivePortfolioConfig,
    LivePortfolioMetrics,
    compute_live_portfolio_metrics,
    load_live_portfolio,
)
from csm.research.exceptions import ReportError
from csm.research.ranking import CrossSectionalRanker
from csm.research.strategy_report import build_strategy_report
from csm.research.strategy_report_models import StrategyReport

if TYPE_CHECKING:
    from csm.adapters import AdapterManager
    from csm.data.store import ParquetStore
    from csm.research.backtest import BacktestConfig, BacktestResult

logger: logging.Logger = logging.getLogger(__name__)
DEFAULT_STRATEGY_ID: str = "csm-set"
DEFAULT_LIVE_PORTFOLIO_PATH: Path = Path("configs/live_portfolio.yaml")


async def run_post_refresh_hook(
    manager: AdapterManager,
    store: ParquetStore,
    summary: dict[str, Any] | None = None,
    live_portfolio_path: Path | None = None,
) -> None:
    """Write equity curve, signal snapshot, daily performance, and portfolio
    snapshot after a successful daily refresh.

    Each adapter write is independently ``try/except``-wrapped so a
    Postgres outage does not block Mongo or Gateway writes.

    Writes split by table semantics:

    - ``db_csm_set.equity_curve`` receives the *actual* live paper-trading
      portfolio NAV series (reconstructed from ``live_portfolio.yaml``
      positions × ``prices_latest``). When the config is missing, the
      equity-curve write is skipped.
    - ``db_gateway.daily_performance`` and
      ``db_gateway.portfolio_snapshot`` receive the same live
      paper-trading portfolio metrics via the gateway ingestion contract.
      When the config is missing, the gateway writes are skipped as well
      (we never write synthetic data into any live-portfolio tables).

    Args:
        manager: The shared ``AdapterManager`` (each slot may be ``None``).
        store: ``ParquetStore`` from which ``prices_latest`` and
            ``features_latest`` are loaded.
        summary: Optional dict from the refresh run with keys
            ``symbols_fetched``, ``failures``, ``duration_seconds``.
        live_portfolio_path: Optional override for the live-portfolio config
            path. Defaults to ``configs/live_portfolio.yaml`` relative to
            cwd.
    """
    strategy_id: str = DEFAULT_STRATEGY_ID
    today: datetime = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    portfolio_path: Path = (
        live_portfolio_path if live_portfolio_path is not None else DEFAULT_LIVE_PORTFOLIO_PATH
    )

    # ---------------------------------------------------------------
    # Load prices_latest once — shared by equity_curve (synthetic universe
    # NAV) and the live-portfolio NAV reconstruction.
    # ---------------------------------------------------------------
    prices: pd.DataFrame = pd.DataFrame()
    if manager.postgres is not None or manager.gateway_client is not None:
        try:
            prices = store.load("prices_latest")
        except Exception:
            logger.warning("post-refresh hook: failed to load prices_latest", exc_info=True)
            prices = pd.DataFrame()

    # ---------------------------------------------------------------
    # 1. Live equity curve — declared here, computed in section 3b
    #    after live_portfolio metrics are available.  The old synthetic
    #    equal-weight universe NAV is intentionally *not* written.
    # ---------------------------------------------------------------
    equity_series: pd.Series | None = None

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
    # 3. Load live-portfolio config and compute the actual paper portfolio
    #    NAV. When the config is missing or the metrics cannot be derived
    #    (e.g. prices_latest empty), the gateway writes below are skipped.
    #    Live config is loaded when either Postgres (equity curve) or
    #    gateway (daily report) is configured — both need it.
    # ---------------------------------------------------------------
    live_config: LivePortfolioConfig | None = None
    live_metrics: LivePortfolioMetrics | None = None
    if manager.gateway_client is not None or manager.postgres is not None:
        try:
            live_config = load_live_portfolio(portfolio_path)
        except Exception:
            logger.warning(
                "post-refresh hook: failed to load live_portfolio config from %s",
                portfolio_path,
                exc_info=True,
            )
        if live_config is not None and not prices.empty:
            try:
                live_metrics = compute_live_portfolio_metrics(live_config, prices)
            except Exception:
                logger.warning(
                    "post-refresh hook: compute_live_portfolio_metrics failed",
                    exc_info=True,
                )

    # ---------------------------------------------------------------
    # 3b. Build per-strategy report (Phase 1 of feature-strategies-report-
    #     metrics). Failures are non-fatal — the daily-performance write
    #     below still runs without the report block.
    # ---------------------------------------------------------------
    if live_metrics is not None and live_config is not None and not prices.empty:
        report: StrategyReport | None = await _build_strategy_report_safe(
            live_config=live_config,
            live_metrics=live_metrics,
            prices=prices,
            store=store,
        )
        if report is not None:
            live_metrics = replace(live_metrics, report=report)
            await _persist_closed_trades_safe(
                manager=manager,
                strategy_id=strategy_id,
                trades=[],  # Phase 1: trade-pairing requires historical fill stream
            )

    # ---------------------------------------------------------------
    # 3c. Live equity curve → Postgres db_csm_set.equity_curve
    #     Reconstruct the actual live portfolio NAV series from the
    #     live_portfolio config and prices_latest.  The series is
    #     reconstructed whenever config + prices are available so it
    #     can feed BOTH the Postgres write AND the gateway payload below.
    # ---------------------------------------------------------------
    if live_config is not None and not prices.empty:
        try:
            equity_series = _reconstruct_live_equity(
                live_config=live_config, prices=prices
            )
        except Exception:
            logger.warning(
                "post-refresh hook: _reconstruct_live_equity failed", exc_info=True
            )
        if (
            manager.postgres is not None
            and equity_series is not None
            and not equity_series.empty
        ):
            try:
                await manager.postgres.write_equity_curve(strategy_id, equity_series)
            except Exception:
                logger.warning(
                    "post-refresh hook: write_equity_curve failed", exc_info=True
                )

    # ---------------------------------------------------------------
    # 4. Daily report → Gateway HTTP ingestion contract.
    #    POST /api/v1/ingest/daily-report carries strategy_metadata,
    #    performance_metrics, current_exposure, and (when built) the
    #    StrategyReport under extended_data.report. The gateway atomically
    #    UPSERTs into db_gateway.daily_performance and
    #    db_gateway.strategy_report_snapshot, then auto-emits the
    #    portfolio_snapshot row when every active strategy has reported
    #    for the day — so we no longer need a separate snapshot write.
    # ---------------------------------------------------------------
    if manager.gateway_client is not None and live_metrics is not None:
        try:
            curve: pd.Series = (
                equity_series if equity_series is not None else pd.Series(dtype="float64")
            )
            payload: dict[str, object] = build_ingestion_payload(
                strategy_id=strategy_id,
                strategy_type=DEFAULT_STRATEGY_TYPE,
                last_updated=today,
                live_metrics=live_metrics,
                equity_curve=curve,
                report=live_metrics.report,
            )
            await manager.gateway_client.post_daily_report(payload)
        except GatewayWriteError:
            logger.warning("post-refresh hook: gateway daily-report POST failed", exc_info=True)
        except Exception:
            logger.warning(
                "post-refresh hook: unexpected error building/posting daily report",
                exc_info=True,
            )
    elif manager.gateway_client is not None:
        logger.info(
            "post-refresh hook: skipping daily-report POST — no live portfolio "
            "metrics available (config=%s, prices_empty=%s)",
            portfolio_path if live_config is None else "loaded",
            prices.empty,
        )


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


async def _build_strategy_report_safe(
    *,
    live_config: LivePortfolioConfig,
    live_metrics: LivePortfolioMetrics,
    prices: pd.DataFrame,
    store: ParquetStore,
) -> StrategyReport | None:
    """Build a :class:`StrategyReport` from the live config + prices panel.

    Failures (empty inputs, missing benchmark column, builder errors) are
    caught and logged at WARNING. The caller proceeds without the report.
    """

    try:
        equity_series: pd.Series = _reconstruct_live_equity(live_config=live_config, prices=prices)
    except Exception:
        logger.warning(
            "post-refresh hook: failed to reconstruct live equity series for report",
            exc_info=True,
        )
        return None
    if equity_series.empty:
        logger.info("post-refresh hook: empty live equity series — skipping report build")
        return None

    settings: Settings = get_settings()
    benchmark_series: pd.Series | None = None
    try:
        benchmark_series = await BenchmarkLoader(settings=settings, store=store).load(
            initial_capital=Decimal(str(live_config.starting_nav))
        )
    except BenchmarkUnavailableError as exc:
        logger.warning(
            "post-refresh hook: benchmark unavailable (%s) — report will omit benchmark",
            exc,
        )
    except Exception:
        logger.warning("post-refresh hook: BenchmarkLoader.load raised unexpectedly", exc_info=True)

    try:
        as_of: datetime = live_metrics.snapshot_time
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        return build_strategy_report(
            trades=[],
            equity=equity_series,
            initial_capital=Decimal(str(live_config.starting_nav)),
            as_of=as_of,
            benchmark=benchmark_series,
        )
    except ReportError:
        logger.warning("post-refresh hook: build_strategy_report rejected inputs", exc_info=True)
    except Exception:
        logger.warning(
            "post-refresh hook: build_strategy_report failed unexpectedly", exc_info=True
        )
    return None


def _reconstruct_live_equity(
    *, live_config: LivePortfolioConfig, prices: pd.DataFrame
) -> pd.Series:
    """Reprice the live config across the full prices panel to derive a NAV series.

    The returned series spans from ``entry_date`` onward and is tz-aware UTC.
    """

    symbols: list[str] = [p.qualified_symbol for p in live_config.positions]
    missing: list[str] = [s for s in symbols if s not in prices.columns]
    if missing:
        logger.warning("live equity reconstruction: missing symbols %s", missing)
        return pd.Series(dtype="float64")

    entry_ts: pd.Timestamp = pd.Timestamp(live_config.entry_date)
    index_tz: Any = prices.index.tz
    if index_tz is not None:
        entry_ts = (
            entry_ts.tz_localize(index_tz) if entry_ts.tz is None else entry_ts.tz_convert(index_tz)
        )
    panel: pd.DataFrame = prices.loc[prices.index >= entry_ts, symbols]
    if panel.empty:
        return pd.Series(dtype="float64")
    shares: pd.Series = pd.Series(
        {p.qualified_symbol: float(p.shares) for p in live_config.positions},
        dtype="float64",
    )
    market_value: pd.Series = panel.mul(shares, axis=1).sum(axis=1)
    nav: pd.Series = market_value + float(live_config.cash)
    if nav.index.tz is None:
        nav.index = nav.index.tz_localize("UTC")
    elif str(nav.index.tz) != "UTC":
        nav.index = nav.index.tz_convert("UTC")
    nav.name = "equity"
    return nav


async def _persist_closed_trades_safe(
    *,
    manager: AdapterManager,
    strategy_id: str,
    trades: list[ClosedTrade],
) -> None:
    """Persist closed-trade rows to ``db_csm_set.trade_history``.

    Soft-skip: writes are best-effort. Failures (e.g. the new columns
    ``entry_price``, ``exit_price``, ``realized_pnl``, ``duration_bars`` not
    yet present on the table — those land in ROADMAP Phase 2) are logged at
    WARNING and never propagate. Empty input is a no-op.
    """

    if manager.postgres is None or not trades:
        return
    rows: pd.DataFrame = pd.DataFrame(
        [
            {
                "time": t.exit_time,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": float(t.qty),
                "price": float(t.exit_price),
                "commission": float(t.commission),
            }
            for t in trades
        ]
    )
    try:
        n: int = await manager.postgres.write_trade_history(strategy_id, rows)
        logger.info("post-refresh hook: wrote %d closed-trade rows", n)
    except Exception:
        logger.warning(
            "post-refresh hook: write_trade_history rejected closed-trade rows "
            "(likely awaiting Phase 2 schema migration)",
            exc_info=True,
        )


__all__: list[str] = [
    "run_post_backtest_hook",
    "run_post_rebalance_hook",
    "run_post_refresh_hook",
]
