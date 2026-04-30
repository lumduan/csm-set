"""Data refresh endpoints."""

import logging

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_settings, get_store
from api.schemas.data import RefreshResult
from api.schemas.errors import ProblemDetail
from csm.config.settings import Settings
from csm.data.loader import OHLCVLoader
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/data", tags=["data"])


@router.post(
    "/refresh",
    response_model=RefreshResult,
    summary="Refresh raw market data",
    description=(
        "Fetch latest OHLCV data for the stored universe from the data provider. "
        "Blocked in public mode."
    ),
    responses={
        200: {
            "description": "Data refresh completed",
            "content": {
                "application/json": {
                    "example": {"refreshed": 50, "requested": 50},
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
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> RefreshResult:
    """Refresh raw OHLCV data for the stored universe."""

    if not store.exists("universe_latest"):
        raise HTTPException(status_code=404, detail="Universe snapshot not found.")
    universe: pd.DataFrame = store.load("universe_latest")
    if "symbol" not in universe.columns:
        raise HTTPException(status_code=400, detail="Universe snapshot missing symbol column.")
    loader: OHLCVLoader = OHLCVLoader(settings=settings)
    symbols: list[str] = universe["symbol"].astype(str).tolist()
    fetched: dict[str, pd.DataFrame] = await loader.fetch_batch(
        symbols=symbols, interval="1D", bars=600
    )
    raw_store: ParquetStore = ParquetStore(settings.data_dir / "raw")
    for symbol, frame in fetched.items():
        raw_store.save(symbol.replace(":", "_"), frame)
    return RefreshResult(refreshed=len(fetched), requested=len(symbols))
