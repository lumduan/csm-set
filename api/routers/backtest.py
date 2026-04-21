"""Backtest endpoints."""

import logging
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.deps import get_store
from csm.data.store import ParquetStore
from csm.research.backtest import BacktestConfig, MomentumBacktest

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/backtest", tags=["backtest"])


def _run_backtest_job(store: ParquetStore, config: BacktestConfig) -> None:
    """Background task wrapper for backtest execution."""

    if not store.exists("features_latest") or not store.exists("prices_latest"):
        logger.warning("Backtest prerequisites missing")
        return
    feature_panel: pd.DataFrame = store.load("features_latest")
    feature_panel["date"] = pd.to_datetime(feature_panel["date"])
    feature_panel = feature_panel.set_index(["date", "symbol"]).sort_index()
    prices: pd.DataFrame = store.load("prices_latest")
    result = MomentumBacktest(store=store).run(
        feature_panel=feature_panel, prices=prices, config=config
    )
    store.save("backtest_summary", pd.DataFrame([result.metrics_dict()]))


@router.post("/run")
async def run_backtest(
    config: BacktestConfig,
    background_tasks: BackgroundTasks,
    store: ParquetStore = Depends(get_store),
) -> dict[str, str]:
    """Enqueue a private-mode backtest run."""

    if not store.exists("features_latest"):
        raise HTTPException(status_code=404, detail="Feature panel not available.")
    job_id: str = uuid4().hex
    background_tasks.add_task(_run_backtest_job, store, config)
    return {"job_id": job_id, "status": "accepted"}
