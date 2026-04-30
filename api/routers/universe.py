"""Universe endpoints."""

from __future__ import annotations

import hashlib
import logging

import pandas as pd
from fastapi import APIRouter, Depends, Request, Response

from api.deps import get_store
from api.logging import get_request_id
from api.retry import RetryExhausted, retry_sync
from api.schemas.errors import ProblemDetail
from api.schemas.universe import UniverseItem, UniverseSnapshot
from csm.data.exceptions import StoreError
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/universe", tags=["universe"])


def _compute_universe_etag(frame: pd.DataFrame) -> str:
    """Compute a weak ETag from the universe's symbol list and sector metadata.

    The ETag changes only when the universe membership or sector classification
    changes — not on every request.
    """
    symbols: list[str] = sorted(
        frame["symbol"].astype(str).tolist() if "symbol" in frame.columns else []
    )
    parts: str = ",".join(symbols) + "|"
    if "sector" in frame.columns and not frame["sector"].isna().all():
        sectors: list[str] = sorted(frame["sector"].dropna().astype(str).tolist())
        parts += ",".join(sectors)
    digest: str = hashlib.sha256(parts.encode()).hexdigest()[:32]
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
        304: {"description": "Not Modified — ETag matches client cache"},
        404: {
            "description": "Universe snapshot not found in the parquet store",
            "model": ProblemDetail,
        },
        500: {"description": "Internal error reading store", "model": ProblemDetail},
    },
)
async def get_universe(
    request: Request,
    response: Response,
    store: ParquetStore = Depends(get_store),
) -> UniverseSnapshot | Response:
    """Return the current stored universe with basic metadata."""

    if not store.exists("universe_latest"):
        logger.warning("Universe snapshot 'universe_latest' not found in store")
        return _problem_response(404, "Universe snapshot not found.")

    try:
        frame: pd.DataFrame = await retry_sync(
            store.load,
            "universe_latest",
            retryable=(OSError, StoreError),
        )
    except (RetryExhausted, StoreError) as exc:
        logger.exception("Failed to load universe snapshot from store")
        return _problem_response(500, f"Failed to read universe data: {exc}")

    if "symbol" not in frame.columns:
        frame = frame.reset_index(names="symbol")

    etag: str = _compute_universe_etag(frame)
    response.headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        logger.info("Universe ETag match — returning 304", extra={"etag": etag})
        return Response(status_code=304, headers={"ETag": etag})

    items: list[UniverseItem] = [UniverseItem(**row) for row in frame.to_dict(orient="records")]
    snapshot = UniverseSnapshot(items=items, count=len(items))

    logger.info("Universe snapshot served", extra={"item_count": len(items), "etag": etag})
    return snapshot
