"""Unit tests for Phase 5.7 — APIKeyMiddleware, is_protected_path, KeyRedactionFilter."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from api.logging import KeyRedactionFilter, install_key_redaction
from api.security import (
    API_KEY_HEADER,
    PROTECTED_PATHS,
    APIKeyMiddleware,
    is_protected_path,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from csm.config.settings import Settings


@pytest.fixture
def reset_settings() -> Iterator[None]:
    """Restore the settings singleton after each test."""

    module = sys.modules["csm.config.settings"]
    original = module.settings
    try:
        yield
    finally:
        module.settings = original


def _install_settings(**overrides: object) -> Settings:
    """Build a Settings instance with the given overrides and patch sys.modules."""

    new = Settings(**overrides)  # type: ignore[arg-type]
    sys.modules["csm.config.settings"].settings = new
    return new


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.post("/api/v1/data/refresh")
    async def refresh() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/universe")
    async def universe() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# is_protected_path
# ---------------------------------------------------------------------------


class TestIsProtectedPath:
    @pytest.mark.parametrize("path", sorted(PROTECTED_PATHS))
    def test_explicit_protected_paths(self, path: str) -> None:
        assert is_protected_path("POST", path) is True
        assert is_protected_path("GET", path) is True

    def test_non_get_on_api_v1_is_protected(self) -> None:
        assert is_protected_path("POST", "/api/v1/some/new/route") is True
        assert is_protected_path("DELETE", "/api/v1/foo") is True
        assert is_protected_path("PUT", "/api/v1/bar") is True
        assert is_protected_path("PATCH", "/api/v1/baz") is True

    def test_get_reads_are_not_protected(self) -> None:
        assert is_protected_path("GET", "/api/v1/universe") is False
        assert is_protected_path("GET", "/api/v1/signals/latest") is False
        assert is_protected_path("GET", "/api/v1/portfolio/current") is False
        assert is_protected_path("GET", "/api/v1/notebooks") is False
        assert is_protected_path("GET", "/api/v1/jobs/abc123") is False

    def test_health_and_docs_not_protected(self) -> None:
        assert is_protected_path("GET", "/health") is False
        assert is_protected_path("GET", "/openapi.json") is False
        assert is_protected_path("GET", "/docs") is False
        assert is_protected_path("GET", "/redoc") is False

    def test_static_notebooks_not_protected(self) -> None:
        assert is_protected_path("GET", "/static/notebooks/foo.html") is False


# ---------------------------------------------------------------------------
# APIKeyMiddleware.dispatch
# ---------------------------------------------------------------------------


class TestAPIKeyMiddleware:
    def test_public_mode_passes_through(self, reset_settings: None) -> None:
        _install_settings(public_mode=True, api_key=SecretStr("secret"))
        app = _make_app()
        with TestClient(app) as client:
            r = client.post("/api/v1/data/refresh")
            assert r.status_code == 200

    def test_private_mode_no_key_passes_through(self, reset_settings: None) -> None:
        _install_settings(public_mode=False, api_key=None)
        app = _make_app()
        with TestClient(app) as client:
            r = client.post("/api/v1/data/refresh")
            assert r.status_code == 200

    def test_private_mode_unprotected_path_passes_through(self, reset_settings: None) -> None:
        _install_settings(public_mode=False, api_key=SecretStr("secret"))
        app = _make_app()
        with TestClient(app) as client:
            r_read = client.get("/api/v1/universe")
            r_health = client.get("/health")
            assert r_read.status_code == 200
            assert r_health.status_code == 200

    def test_private_mode_missing_header_returns_401(self, reset_settings: None) -> None:
        _install_settings(public_mode=False, api_key=SecretStr("secret"))
        app = _make_app()
        with TestClient(app) as client:
            r = client.post("/api/v1/data/refresh")
            assert r.status_code == 401
            body = r.json()
            assert "Missing" in body["detail"]
            assert body["detail"].endswith("X-API-Key header.")

    def test_private_mode_wrong_header_returns_401(self, reset_settings: None) -> None:
        _install_settings(public_mode=False, api_key=SecretStr("secret"))
        app = _make_app()
        with TestClient(app) as client:
            r = client.post("/api/v1/data/refresh", headers={API_KEY_HEADER: "wrong"})
            assert r.status_code == 401
            body = r.json()
            assert "Invalid" in body["detail"]

    def test_private_mode_correct_header_passes_through(self, reset_settings: None) -> None:
        _install_settings(public_mode=False, api_key=SecretStr("secret"))
        app = _make_app()
        with TestClient(app) as client:
            r = client.post("/api/v1/data/refresh", headers={API_KEY_HEADER: "secret"})
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# KeyRedactionFilter
# ---------------------------------------------------------------------------


class TestKeyRedactionFilter:
    def test_redacts_secret_in_msg(self) -> None:
        f = KeyRedactionFilter("topsecret")
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="API key was topsecret here",
            args=None,
            exc_info=None,
        )
        assert f.filter(record) is True
        assert "topsecret" not in record.getMessage()
        assert "***REDACTED***" in record.getMessage()

    def test_redacts_secret_in_string_args(self) -> None:
        f = KeyRedactionFilter("topsecret")
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="got %s",
            args=("topsecret",),
            exc_info=None,
        )
        f.filter(record)
        assert record.args == ("***REDACTED***",)

    def test_does_not_modify_non_string_args(self) -> None:
        f = KeyRedactionFilter("topsecret")
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="count=%d",
            args=(42,),
            exc_info=None,
        )
        f.filter(record)
        assert record.args == (42,)

    def test_noop_when_secret_empty(self) -> None:
        f = KeyRedactionFilter("")
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="anything goes",
            args=None,
            exc_info=None,
        )
        f.filter(record)
        assert record.getMessage() == "anything goes"

    def test_unrelated_message_passes_through(self) -> None:
        f = KeyRedactionFilter("topsecret")
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="nothing sensitive",
            args=None,
            exc_info=None,
        )
        f.filter(record)
        assert record.getMessage() == "nothing sensitive"


class TestInstallKeyRedaction:
    def _drop_filters(self) -> None:
        root = logging.getLogger()
        for f in list(root.filters):
            if isinstance(f, KeyRedactionFilter):
                root.removeFilter(f)

    def test_install_with_none_is_noop(self) -> None:
        self._drop_filters()
        try:
            install_key_redaction(None)
            root = logging.getLogger()
            assert not any(isinstance(f, KeyRedactionFilter) for f in root.filters)
        finally:
            self._drop_filters()

    def test_install_with_secret_attaches_filter(self) -> None:
        self._drop_filters()
        try:
            install_key_redaction(SecretStr("xyz"))
            root = logging.getLogger()
            attached = [f for f in root.filters if isinstance(f, KeyRedactionFilter)]
            assert len(attached) == 1
        finally:
            self._drop_filters()

    def test_install_with_empty_secret_is_noop(self) -> None:
        self._drop_filters()
        try:
            install_key_redaction(SecretStr(""))
            root = logging.getLogger()
            assert not any(isinstance(f, KeyRedactionFilter) for f in root.filters)
        finally:
            self._drop_filters()


def _silence_unused(_x: Any) -> None:
    pass
