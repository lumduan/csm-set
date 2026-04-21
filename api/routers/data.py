"""Data refresh endpoints."""

import logging

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_settings, get_store
from csm.config.settings import Settings
from csm.data.loader import OHLCVLoader
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/data", tags=["data"])


@router.post("/refresh")
async def refresh_data(
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> dict[str, object]:
    """Refresh raw OHLCV data for the stored universe."""

    if not store.exists("universe_latest"):
        raise HTTPException(status_code=404, detail="Universe snapshot not found.")
    universe: pd.DataFrame = store.load("universe_latest")
    if "symbol" not in universe.columns:
        raise HTTPException(status_code=400, detail="Universe snapshot missing symbol column.")
    loader: OHLCVLoader = OHLCVLoader(settings=settings)
    symbols: list[str] = universe["symbol"].astype(str).tolist()
    fetched: dict[str, pd.DataFrame] = await loader.fetch_batch(symbols=symbols, interval="1D", bars=600)
    raw_store: ParquetStore = ParquetStore(settings.data_dir / "raw")
    for symbol, frame in fetched.items():
        raw_store.save(symbol.replace(":", "_"), frame)
    return {"refreshed": len(fetched), "requested": len(symbols)}
