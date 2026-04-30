"""Portfolio endpoints."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_settings, get_store
from api.schemas.errors import ProblemDetail
from api.schemas.portfolio import Holding, PortfolioSnapshot
from csm.config.settings import Settings
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get(
    "/current",
    response_model=PortfolioSnapshot,
    summary="Get current portfolio",
    description=(
        "Return the current portfolio snapshot with holdings and summary metrics. "
        "In public mode, reads from a pre-computed backtest summary JSON. "
        "In private mode, reads from the live portfolio state."
    ),
    responses={
        200: {
            "description": "Portfolio snapshot returned successfully",
            "content": {
                "application/json": {
                    "example": {
                        "as_of": "2026-04-21T00:00:00+07:00",
                        "holdings": [
                            {"symbol": "SET001", "weight": 0.02, "sector": "BANK"},
                            {"symbol": "SET002", "weight": 0.015, "sector": "TECH"},
                        ],
                        "summary_metrics": {
                            "cagr": 0.15,
                            "sharpe": 1.2,
                            "sortino": 1.8,
                        },
                    },
                },
            },
        },
        404: {
            "description": "No portfolio data found",
            "model": ProblemDetail,
        },
        500: {
            "description": "Portfolio payload is malformed",
            "model": ProblemDetail,
        },
    },
)
async def get_current_portfolio(
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> PortfolioSnapshot:
    """Return current portfolio summary data."""

    if settings.public_mode:
        path: Path = settings.results_dir / "backtest" / "summary.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No pre-computed portfolio summary found.")
        content: str = await asyncio.to_thread(path.read_text)
        payload: object = json.loads(content)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Portfolio payload is malformed.")
        data: dict[str, Any] = {str(key): value for key, value in payload.items()}
        generated_at: str = str(data.pop("generated_at", datetime.now(UTC).isoformat()))
        data.pop("config", None)
        summary_metrics: dict[str, float] = {
            str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))
        }
        return PortfolioSnapshot(
            as_of=generated_at,
            holdings=[],
            summary_metrics=summary_metrics,
        )

    if not store.exists("portfolio_current"):
        raise HTTPException(status_code=404, detail="Portfolio snapshot not found.")
    frame: pd.DataFrame = store.load("portfolio_current")
    holdings: list[Holding] = []
    for _, row in frame.iterrows():
        row_dict = row.to_dict()
        weight = float(row_dict.get("weight", 0.0))
        sector = None
        if "sector" in row_dict:
            sector_val = row_dict["sector"]
            if pd.notna(sector_val):
                sector = str(sector_val)
        holdings.append(
            Holding(
                symbol=str(row_dict.get("symbol", "")),
                weight=weight,
                sector=sector,
            )
        )
    return PortfolioSnapshot(
        as_of=datetime.now(UTC).isoformat(),
        holdings=holdings,
    )
