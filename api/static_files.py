"""StaticFiles subclass with Cache-Control headers and a 404 fallback page."""

from __future__ import annotations

import logging
import os
from os import stat_result
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

if TYPE_CHECKING:
    from os import PathLike

    from starlette.types import Scope

logger: logging.Logger = logging.getLogger(__name__)

_DEFAULT_FALLBACK: Path = Path(__file__).resolve().parent / "static" / "notebook_missing.html"
_CACHE_CONTROL: str = "public, max-age=300"


class NotebookStaticFiles(StaticFiles):
    """StaticFiles subclass that adds Cache-Control and a 404 fallback page.

    Intended for serving pre-rendered notebook HTML files under
    ``/static/notebooks/``.  Every response receives
    ``Cache-Control: public, max-age=300``.  When a file is not found the
    mount returns a friendly HTML fallback page (with status 404) instead of
    Starlette's default plain-text response.

    The served directory is resolved from ``Settings.results_dir / "notebooks"``
    on every request so that test-level settings patches are honoured.
    """

    def __init__(
        self,
        *,
        directory: Path | str | None = None,
        fallback_path: Path | str | None = None,
        **kwargs: object,
    ) -> None:
        self._explicit_directory: str | None = (
            os.fspath(directory) if directory is not None else None
        )
        self._fallback_path: Path = (
            Path(fallback_path) if fallback_path is not None else _DEFAULT_FALLBACK
        )
        super().__init__(
            directory=directory if directory is not None else ".",
            check_dir=False,
            **kwargs,  # type: ignore[arg-type]
        )

    def _resolve_directory(self) -> str:
        """Return the notebooks directory from current settings."""
        import sys

        settings_mod = sys.modules["csm.config.settings"]
        settings: object = settings_mod.settings
        return os.fspath(settings.results_dir / "notebooks")  # type: ignore[attr-defined]

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        """Resolve the directory dynamically on every lookup."""
        directory: str = (
            self._explicit_directory
            if self._explicit_directory is not None
            else self._resolve_directory()
        )
        joined_path = os.path.join(directory, path)
        full_path = os.path.realpath(joined_path)
        real_directory = os.path.realpath(directory)
        if os.path.commonpath([full_path, real_directory]) != real_directory:
            return "", None
        try:
            return full_path, os.stat(full_path)
        except (FileNotFoundError, NotADirectoryError):
            return "", None

    def file_response(
        self,
        full_path: PathLike[str] | str,
        stat_result: stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        """Add Cache-Control to every file response (200 and 304)."""
        response: Response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = _CACHE_CONTROL
        return response

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Intercept 404 and serve the fallback HTML page."""
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise

        try:
            content: bytes = await anyio.to_thread.run_sync(self._fallback_path.read_bytes)
        except OSError:
            logger.warning("Fallback page missing: %s", self._fallback_path)
            raise HTTPException(status_code=404) from None

        logger.info("Serving fallback page for missing notebook: %s", path)
        return Response(
            content=content,
            status_code=404,
            media_type="text/html",
            headers={"Cache-Control": _CACHE_CONTROL},
        )
