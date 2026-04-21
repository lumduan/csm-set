"""Universe endpoints."""

import logging

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_store
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/universe", tags=["universe"])


@router.get("")
async def get_universe(
    store: ParquetStore = Depends(get_store),
) -> dict[str, list[dict[str, object]]]:
    """Return the current stored universe with basic metadata."""

    if not store.exists("universe_latest"):
        raise HTTPException(status_code=404, detail="Universe snapshot not found.")
    frame: pd.DataFrame = store.load("universe_latest")
    if "symbol" not in frame.columns:
        frame = frame.reset_index(names="symbol")
    return {"items": frame.to_dict(orient="records")}
