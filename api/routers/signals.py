"""Signal endpoints."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_settings, get_store
from api.schemas.errors import ProblemDetail
from api.schemas.signals import SignalRanking, SignalRow
from csm.config.settings import Settings
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline
from csm.research.ranking import CrossSectionalRanker

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/signals", tags=["signals"])


@router.get(
    "/latest",
    response_model=SignalRanking,
    summary="Get latest signal ranking",
    description=(
        "Return the latest cross-sectional signal ranking. "
        "In public mode, reads from a pre-computed JSON export. "
        "In private mode, computes live from the feature pipeline."
    ),
    responses={
        200: {
            "description": "Signals ranked successfully",
            "content": {
                "application/json": {
                    "example": {
                        "as_of": "2026-04-21",
                        "rankings": [
                            {
                                "symbol": "SET001",
                                "mom_12_1": 0.15,
                                "mom_12_1_rank": 0.95,
                                "mom_12_1_quintile": 5,
                            },
                            {
                                "symbol": "SET002",
                                "mom_12_1": 0.08,
                                "mom_12_1_rank": 0.72,
                                "mom_12_1_quintile": 4,
                            },
                        ],
                    },
                },
            },
        },
        404: {
            "description": "No pre-computed signals file found",
            "model": ProblemDetail,
        },
        500: {
            "description": "Signals payload is malformed",
            "model": ProblemDetail,
        },
    },
)
async def get_latest_signals(
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> SignalRanking:
    """Return the latest signal ranking in public or private mode."""

    if settings.public_mode:
        path: Path = settings.results_dir / "signals" / "latest_ranking.json"
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="No pre-computed signals. Run scripts/export_results.py first.",
            )
        content: str = await asyncio.to_thread(path.read_text)
        payload: object = json.loads(content)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Signals payload is malformed.")
        raw_rankings: list[dict[str, Any]] = payload.get("rankings", [])
        as_of: str = str(payload.get("as_of", ""))
        rankings: list[SignalRow] = [SignalRow(**r) for r in raw_rankings]
        return SignalRanking(as_of=as_of, rankings=rankings)

    pipeline: FeaturePipeline = FeaturePipeline(store=store)
    feature_panel = pipeline.load_latest()
    latest_date = feature_panel.index.get_level_values("date").max()
    ranking = CrossSectionalRanker().rank(feature_panel, latest_date)
    ranking_items: list[dict[str, Any]] = ranking.to_dict(orient="records")
    rankings = [SignalRow(**r) for r in ranking_items]
    return SignalRanking(
        as_of=str(latest_date.strftime("%Y-%m-%d")),
        rankings=rankings,
    )
