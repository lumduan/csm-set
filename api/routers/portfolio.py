"""Portfolio endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Request, Response

from api.deps import get_settings, get_store
from api.logging import get_request_id
from api.retry import RetryExhausted, retry_async, retry_sync
from api.schemas.errors import ProblemDetail
from api.schemas.portfolio import Holding, PortfolioSnapshot
from csm.config.settings import Settings
from csm.data.exceptions import StoreError
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _compute_portfolio_etag(snapshot: PortfolioSnapshot) -> str:
    """Compute a weak ETag from the stable portfolio fields.

    The ``as_of`` timestamp is excluded because it changes on every
    private-mode request (set to ``now()``), which would defeat caching.
    """
    stable = snapshot.model_dump(exclude={"as_of"})
    digest: str = hashlib.sha256(
        json.dumps(stable, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]
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
    "/current",
    response_model=PortfolioSnapshot,
    summary="Get current portfolio",
    description=(
        "Return the current portfolio snapshot with holdings, summary metrics, "
        "market regime, and circuit breaker state. "
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
                        "regime": "BULL",
                        "breaker_state": "NORMAL",
                        "equity_fraction": 1.0,
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
        304: {"description": "Not Modified — ETag matches client cache"},
        404: {"description": "No portfolio data found", "model": ProblemDetail},
        500: {
            "description": "Portfolio payload is malformed or store read failed",
            "model": ProblemDetail,
        },
    },
)
async def get_current_portfolio(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> PortfolioSnapshot | Response:
    """Return current portfolio summary data."""

    regime: str = "NEUTRAL"
    breaker_state: str = "NORMAL"
    equity_fraction: float = 1.0

    if settings.public_mode:
        path: Path = settings.results_dir / "backtest" / "summary.json"
        if not path.exists():
            logger.warning("Portfolio summary JSON not found at %s", path)
            return _problem_response(404, "No pre-computed portfolio summary found.")

        try:
            content: str = await retry_async(
                asyncio.to_thread,
                path.read_text,
                retryable=(OSError,),
            )
        except (RetryExhausted, OSError) as exc:
            logger.exception("Failed to read portfolio summary JSON from %s", path)
            return _problem_response(500, f"Failed to read portfolio summary file: {exc}")

        try:
            payload: object = json.loads(content)
        except json.JSONDecodeError:
            logger.exception("Malformed portfolio summary JSON at %s", path)
            return _problem_response(500, "Portfolio payload is malformed JSON.")

        if not isinstance(payload, dict):
            logger.error("Portfolio payload is not a dict: %s", type(payload).__name__)
            return _problem_response(500, "Portfolio payload is malformed.")

        data: dict[str, Any] = {str(key): value for key, value in payload.items()}
        generated_at: str = str(data.pop("generated_at", ""))
        data.pop("config", None)
        summary_metrics: dict[str, float] = {
            str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))
        }
        snapshot = PortfolioSnapshot(
            as_of=generated_at,
            regime=regime,
            breaker_state=breaker_state,
            equity_fraction=equity_fraction,
            holdings=[],
            summary_metrics=summary_metrics,
        )
    else:
        if not store.exists("portfolio_current"):
            logger.warning("Portfolio snapshot 'portfolio_current' not found in store")
            return _problem_response(404, "Portfolio snapshot not found.")

        try:
            frame: pd.DataFrame = await retry_sync(
                store.load,
                "portfolio_current",
                retryable=(OSError, StoreError),
            )
        except (RetryExhausted, StoreError) as exc:
            logger.exception("Failed to load portfolio snapshot from store")
            return _problem_response(500, f"Failed to read portfolio data: {exc}")

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

        # Load portfolio state (regime, breaker, equity fraction) if available
        if store.exists("portfolio_state"):
            try:
                state_frame: pd.DataFrame = await retry_sync(
                    store.load,
                    "portfolio_state",
                    retryable=(OSError, StoreError),
                )
                if not state_frame.empty:
                    row = state_frame.iloc[0]
                    regime = str(row.get("regime", "NEUTRAL"))
                    breaker_state = str(row.get("breaker_state", "NORMAL"))
                    equity_fraction = float(row.get("equity_fraction", 1.0))
            except (RetryExhausted, StoreError, KeyError, ValueError):
                logger.warning("Could not load portfolio_state, using defaults", exc_info=True)

        snapshot = PortfolioSnapshot(
            as_of=pd.Timestamp.now(tz="Asia/Bangkok").isoformat(),
            regime=regime,
            breaker_state=breaker_state,
            equity_fraction=equity_fraction,
            holdings=holdings,
        )

    etag: str = _compute_portfolio_etag(snapshot)
    response.headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        logger.info(
            "Portfolio ETag match — returning 304",
            extra={"etag": etag, "as_of": snapshot.as_of},
        )
        return Response(status_code=304, headers={"ETag": etag})

    logger.info(
        "Portfolio snapshot served",
        extra={
            "etag": etag,
            "as_of": snapshot.as_of,
            "holding_count": len(snapshot.holdings),
            "regime": snapshot.regime,
            "breaker_state": snapshot.breaker_state,
        },
    )
    return snapshot
