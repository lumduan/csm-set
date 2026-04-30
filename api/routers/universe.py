"""Universe endpoints."""

import logging

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_store
from api.schemas.errors import ProblemDetail
from api.schemas.universe import UniverseItem, UniverseSnapshot
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/universe", tags=["universe"])


@router.get(
    "",
    response_model=UniverseSnapshot,
    summary="Get current universe",
    description="Return the current stored universe with constituent metadata.",
    responses={
        200: {
            "description": "Universe snapshot returned successfully",
            "content": {
                "application/json": {
                    "example": {
                        "items": [
                            {"symbol": "SET001", "sector": "BANK"},
                            {"symbol": "SET002", "sector": "TECH"},
                        ],
                        "count": 2,
                    },
                },
            },
        },
        404: {
            "description": "Universe snapshot not found in the parquet store",
            "model": ProblemDetail,
        },
    },
)
async def get_universe(
    store: ParquetStore = Depends(get_store),
) -> UniverseSnapshot:
    """Return the current stored universe with basic metadata."""

    if not store.exists("universe_latest"):
        raise HTTPException(status_code=404, detail="Universe snapshot not found.")
    frame: pd.DataFrame = store.load("universe_latest")
    if "symbol" not in frame.columns:
        frame = frame.reset_index(names="symbol")
    items: list[UniverseItem] = [UniverseItem(**row) for row in frame.to_dict(orient="records")]
    return UniverseSnapshot(items=items, count=len(items))
