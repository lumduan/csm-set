"""Backtest endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from ulid import ULID

from api.deps import get_adapter_manager, get_jobs, get_store
from api.jobs import JobKind, JobRegistry
from api.logging import get_request_id
from api.schemas.backtest import BacktestRunResponse
from api.schemas.errors import ProblemDetail
from csm.data.store import ParquetStore
from csm.research.backtest import BacktestConfig, MomentumBacktest

if TYPE_CHECKING:
    from csm.adapters import AdapterManager
    from csm.research.backtest import BacktestResult

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/backtest", tags=["backtest"])


async def _backtest_runner(
    store: ParquetStore,
    config: BacktestConfig,
    adapters: AdapterManager | None = None,
) -> dict[str, object]:
    """Run a momentum backtest, persist the summary, and call the post-backtest hook.

    Wrapped in :func:`asyncio.to_thread` because ``MomentumBacktest.run``
    is CPU-bound and synchronous.
    """
    run_id: str = str(ULID())

    def _run() -> BacktestResult:
        feature_panel = store.load("features_latest")
        feature_panel["date"] = pd.to_datetime(feature_panel["date"])
        feature_panel = feature_panel.set_index(["date", "symbol"]).sort_index()
        prices = store.load("prices_latest")
        result = MomentumBacktest(store=store).run(
            feature_panel=feature_panel, prices=prices, config=config
        )
        return result

    import pandas as pd

    result = await asyncio.to_thread(_run)
    store.save("backtest_summary", pd.DataFrame([result.metrics_dict()]))

    if adapters is not None:
        from csm.adapters.hooks import run_post_backtest_hook

        await run_post_backtest_hook(
            manager=adapters,
            run_id=run_id,
            strategy_id="csm-set",
            config=config,
            result=result,
        )

    return result.metrics_dict()


@router.post(
    "/run",
    response_model=BacktestRunResponse,
    summary="Run a backtest",
    description=(
        "Enqueue a private-mode backtest run with the given configuration. "
        "Returns a job ID immediately — poll ``GET /api/v1/jobs/{job_id}`` "
        "for completion status. Blocked in public mode."
    ),
    responses={
        200: {
            "description": "Backtest job accepted",
            "content": {
                "application/json": {
                    "example": {"job_id": "01JQEXAMPLE0000000000000000", "status": "accepted"},
                },
            },
        },
        404: {
            "description": "Feature panel not available for backtest",
            "model": ProblemDetail,
        },
        403: {
            "description": "Disabled in public mode",
            "model": ProblemDetail,
        },
    },
)
async def run_backtest(
    config: BacktestConfig,
    request: Request,
    jobs: JobRegistry = Depends(get_jobs),
    store: ParquetStore = Depends(get_store),
) -> BacktestRunResponse:
    """Enqueue a private-mode backtest run."""

    if not store.exists("features_latest"):
        raise HTTPException(status_code=404, detail="Feature panel not available.")

    adapters = get_adapter_manager(request)
    record = await jobs.submit(
        JobKind.BACKTEST_RUN,
        _backtest_runner,
        request_id=get_request_id(),
        store=store,
        config=config,
        adapters=adapters,
    )
    logger.info("Backtest job %s accepted", record.job_id)
    return BacktestRunResponse(job_id=record.job_id, status=record.status)
