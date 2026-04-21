"""Signal endpoints."""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_settings, get_store
from csm.config.settings import Settings
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline
from csm.research.ranking import CrossSectionalRanker

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/latest")
async def get_latest_signals(
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> dict[str, object]:
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
        return {str(key): value for key, value in payload.items()}

    pipeline: FeaturePipeline = FeaturePipeline(store=store)
    feature_panel = pipeline.load_latest()
    latest_date = feature_panel.index.get_level_values("date").max()
    ranking = CrossSectionalRanker().rank(feature_panel, latest_date)
    return {
        "as_of": latest_date.strftime("%Y-%m-%d"),
        "rankings": ranking.to_dict(orient="records"),
    }
