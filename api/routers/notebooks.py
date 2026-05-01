"""Notebook index endpoint."""

from __future__ import annotations

import hashlib
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response

from api.logging import get_request_id
from api.schemas.errors import ProblemDetail
from api.schemas.notebooks import NotebookEntry, NotebookIndex

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/notebooks", tags=["notebooks"])


def _settings() -> Any:  # noqa: ANN401
    """Return the current Settings singleton, respecting test-level patches."""
    return sys.modules["csm.config.settings"].settings


def _compute_index_etag(entries: list[NotebookEntry]) -> str:
    """Compute a weak ETag from sorted notebook metadata."""
    parts: str = "|".join(f"{e.name}:{e.size_bytes}:{e.last_modified}" for e in entries)
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
    response_model=NotebookIndex,
    summary="List available notebooks",
    description="Return an index of pre-rendered analysis notebooks available for browsing.",
    responses={
        200: {
            "description": "Notebook index returned successfully",
            "content": {
                "application/json": {
                    "example": {
                        "items": [
                            {
                                "name": "01_data_exploration.html",
                                "path": "/static/notebooks/01_data_exploration.html",
                                "size_bytes": 395264,
                                "last_modified": "2026-04-30T12:00:00Z",
                            },
                        ],
                    },
                },
            },
        },
        304: {"description": "Not Modified — ETag matches client cache"},
        500: {"description": "Internal error reading notebook directory", "model": ProblemDetail},
    },
)
async def list_notebooks(request: Request, response: Response) -> NotebookIndex | Response:
    """Return an index of available pre-rendered notebook HTML files."""

    notebooks_dir: Path = _settings().results_dir / "notebooks"

    if not notebooks_dir.is_dir():
        logger.info("Notebooks directory does not exist, returning empty index")
        return NotebookIndex(items=[])

    resolved_root: Path = notebooks_dir.resolve()

    entries: list[NotebookEntry] = []
    try:
        for html_file in sorted(notebooks_dir.glob("*.html")):
            resolved: Path = html_file.resolve()
            # Directory traversal defence: reject files that resolve outside the root.
            try:
                resolved.relative_to(resolved_root)
            except ValueError:
                logger.warning(
                    "Skipping notebook outside served root: %s",
                    html_file,
                    extra={"resolved": str(resolved), "root": str(resolved_root)},
                )
                continue

            try:
                st = html_file.stat()
            except OSError:
                logger.warning("Skipping unreadable notebook: %s", html_file)
                continue

            last_modified: str = datetime.fromtimestamp(st.st_mtime, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            entries.append(
                NotebookEntry(
                    name=html_file.name,
                    path=f"/static/notebooks/{html_file.name}",
                    size_bytes=st.st_size,
                    last_modified=last_modified,
                )
            )
    except OSError as exc:
        logger.exception("Failed to scan notebook directory")
        return _problem_response(500, f"Failed to read notebook directory: {exc}")

    etag: str = _compute_index_etag(entries)
    response.headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        logger.info("Notebook index ETag match — returning 304", extra={"etag": etag})
        return Response(status_code=304, headers={"ETag": etag})

    logger.info("Notebook index served", extra={"count": len(entries), "etag": etag})
    return NotebookIndex(items=entries)
