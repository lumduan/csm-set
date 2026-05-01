"""Data refresh endpoints."""

from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_jobs, get_settings, get_store
from api.jobs import JobKind, JobRegistry
from api.logging import get_request_id
from api.schemas.data import RefreshResult
from api.schemas.errors import ProblemDetail
from csm.config.settings import Settings
from csm.data.loader import OHLCVLoader
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/data", tags=["data"])


async def _refresh_runner(settings: Settings, store: ParquetStore) -> dict[str, object]:
    """Fetch latest OHLCV data and write to the raw store.

    Returns a summary dict stored on ``JobRecord.summary``.
    """
    universe: pd.DataFrame = store.load("universe_latest")
    symbols: list[str] = universe["symbol"].astype(str).tolist()
    loader: OHLCVLoader = OHLCVLoader(settings=settings)
    fetched: dict[str, pd.DataFrame] = await loader.fetch_batch(
        symbols=symbols, interval="1D", bars=600
    )
    raw_store: ParquetStore = ParquetStore(settings.data_dir / "raw")
    for symbol, frame in fetched.items():
        raw_store.save(symbol.replace(":", "_"), frame)
    return {"refreshed": len(fetched), "requested": len(symbols)}


@router.post(
    "/refresh",
    response_model=RefreshResult,
    summary="Refresh raw market data",
    description=(
        "Enqueue a data refresh job for the stored universe. "
        "Returns a job ID immediately — poll ``GET /api/v1/jobs/{job_id}`` "
        "for completion status. Blocked in public mode."
    ),
    responses={
        200: {
            "description": "Refresh job accepted",
            "content": {
                "application/json": {
                    "example": {"job_id": "01JQEXAMPLE0000000000000000", "status": "accepted"},
                },
            },
        },
        404: {
            "description": "Universe snapshot not found",
            "model": ProblemDetail,
        },
        400: {
            "description": "Universe snapshot is malformed (missing symbol column)",
            "model": ProblemDetail,
        },
        403: {
            "description": "Disabled in public mode",
            "model": ProblemDetail,
        },
    },
)
async def refresh_data(
    jobs: JobRegistry = Depends(get_jobs),
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> RefreshResult:
    """Enqueue a data refresh job for the stored universe."""

    if not store.exists("universe_latest"):
        raise HTTPException(status_code=404, detail="Universe snapshot not found.")
    universe: pd.DataFrame = store.load("universe_latest")
    if "symbol" not in universe.columns:
        raise HTTPException(status_code=400, detail="Universe snapshot missing symbol column.")

    record = await jobs.submit(
        JobKind.DATA_REFRESH,
        _refresh_runner,
        request_id=get_request_id(),
        settings=settings,
        store=store,
    )
    logger.info("Data refresh job %s accepted (%d symbols)", record.job_id, len(universe))
    return RefreshResult(job_id=record.job_id, status=record.status)
