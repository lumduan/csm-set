"""Signal endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from api.deps import get_settings, get_store
from api.logging import get_request_id
from api.retry import RetryExhausted, retry_async, retry_sync
from api.schemas.errors import ProblemDetail
from api.schemas.signals import SignalRanking, SignalRow
from csm.config.settings import Settings
from csm.data.exceptions import StoreError
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline
from csm.research.ranking import CrossSectionalRanker

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/signals", tags=["signals"])


def _compute_signal_etag(snapshot: SignalRanking) -> str:
    """Compute a weak ETag from the serialized ranking content."""
    digest: str = hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()[:32]
    return f'W/"{digest}"'


def _problem_response(status_code: int, detail: str) -> Response:
    """Build a JSON problem-detail response with request-id."""
    return Response(
        status_code=status_code,
        content=ProblemDetail(
            detail=detail,
            request_id=get_request_id(),
        ).model_dump_json(),
        media_type="application/problem+json",
    )


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
        304: {"description": "Not Modified — ETag matches client cache"},
        404: {"description": "No pre-computed signals file found", "model": ProblemDetail},
        500: {
            "description": "Signals payload is malformed or store read failed",
            "model": ProblemDetail,
        },
    },
)
async def get_latest_signals(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> SignalRanking | Response:
    """Return the latest signal ranking in public or private mode."""

    if settings.public_mode:
        path: Path = settings.results_dir / "signals" / "latest_ranking.json"
        if not path.exists():
            logger.warning("Signals JSON not found at %s", path)
            return _problem_response(
                404, "No pre-computed signals. Run scripts/export_results.py first."
            )

        try:
            content: str = await retry_async(
                asyncio.to_thread,
                path.read_text,
                retryable=(OSError,),
            )
        except (RetryExhausted, OSError) as exc:
            logger.exception("Failed to read signals JSON from %s", path)
            return _problem_response(500, f"Failed to read signals file: {exc}")

        try:
            payload: object = json.loads(content)
        except json.JSONDecodeError:
            logger.exception("Malformed signals JSON at %s", path)
            return _problem_response(500, "Signals payload is malformed JSON.")

        if not isinstance(payload, dict):
            logger.error("Signals payload is not a dict: %s", type(payload).__name__)
            return _problem_response(500, "Signals payload is malformed.")

        raw_rankings: list[dict[str, Any]] = payload.get("rankings", [])
        as_of: str = str(payload.get("as_of", ""))
        rankings: list[SignalRow] = [SignalRow(**r) for r in raw_rankings]
        snapshot = SignalRanking(as_of=as_of, rankings=rankings)
    else:
        try:
            pipeline: FeaturePipeline = FeaturePipeline(store=store)
            feature_panel = await retry_sync(
                pipeline.load_latest,
                retryable=(OSError, StoreError, KeyError),
            )
        except (RetryExhausted, StoreError) as exc:
            logger.exception("Failed to load feature panel from store")
            return _problem_response(500, f"Failed to load features: {exc}")
        except Exception as exc:
            logger.exception("Unexpected error loading features")
            return _problem_response(500, f"Failed to load features: {exc}")

        latest_date = feature_panel.index.get_level_values("date").max()
        ranking = CrossSectionalRanker().rank(feature_panel, latest_date)
        ranking_items: list[dict[str, Any]] = ranking.to_dict(orient="records")
        rankings = [SignalRow(**r) for r in ranking_items]
        snapshot = SignalRanking(
            as_of=str(latest_date.strftime("%Y-%m-%d")),
            rankings=rankings,
        )

    etag: str = _compute_signal_etag(snapshot)
    response.headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        logger.info(
            "Signals ETag match — returning 304",
            extra={"etag": etag, "as_of": snapshot.as_of},
        )
        return Response(status_code=304, headers={"ETag": etag})

    logger.info(
        "Signals ranking served",
        extra={"etag": etag, "as_of": snapshot.as_of, "ranking_count": len(snapshot.rankings)},
    )
    return snapshot
