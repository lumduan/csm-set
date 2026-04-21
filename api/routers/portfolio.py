"""Portfolio endpoints."""

import asyncio
import json
import logging
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_settings, get_store
from csm.config.settings import Settings
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/current")
async def get_current_portfolio(
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> dict[str, object]:
    """Return current portfolio summary data."""

    if settings.public_mode:
        path: Path = settings.results_dir / "backtest" / "summary.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No pre-computed portfolio summary found.")
        content: str = await asyncio.to_thread(path.read_text)
        payload: object = json.loads(content)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Portfolio payload is malformed.")
        return {str(key): value for key, value in payload.items()}

    if not store.exists("portfolio_current"):
        raise HTTPException(status_code=404, detail="Portfolio snapshot not found.")
    frame: pd.DataFrame = store.load("portfolio_current")
    return {"items": frame.to_dict(orient="records")}
