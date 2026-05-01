"""Unit tests for api.static_files.NotebookStaticFiles."""

from __future__ import annotations

from pathlib import Path

import pytest
from api.static_files import NotebookStaticFiles
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    d = tmp_path / "notebooks"
    d.mkdir()
    return d


@pytest.fixture
def fallback_file(tmp_path: Path) -> Path:
    f = tmp_path / "fallback.html"
    f.write_text("<!DOCTYPE html><html><body>Not Found</body></html>")
    return f


@pytest.fixture
def client(static_dir: Path, fallback_file: Path) -> TestClient:
    app = FastAPI()
    app.mount(
        "/static/notebooks",
        NotebookStaticFiles(directory=static_dir, fallback_path=fallback_file),
        name="notebooks",
    )
    return TestClient(app, raise_server_exceptions=False)


class TestNotebookStaticFilesHeaders:
    def test_cache_control_on_success(self, static_dir: Path, client: TestClient) -> None:
        (static_dir / "test.html").write_text("<html>hello</html>")

        resp = client.get("/static/notebooks/test.html")
        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == "public, max-age=300"
        assert "text/html" in resp.headers["Content-Type"]
        assert resp.text == "<html>hello</html>"

    def test_cache_control_on_304(self, static_dir: Path, client: TestClient) -> None:
        (static_dir / "test.html").write_text("<html>hello</html>")

        resp1 = client.get("/static/notebooks/test.html")
        etag: str = resp1.headers["ETag"]
        assert resp1.status_code == 200

        resp2 = client.get(
            "/static/notebooks/test.html",
            headers={"If-None-Match": etag},
        )
        assert resp2.status_code == 304
        assert resp2.headers["Cache-Control"] == "public, max-age=300"


class TestNotebookStaticFilesFallback:
    def test_missing_file_returns_fallback(self, client: TestClient) -> None:
        resp = client.get("/static/notebooks/nonexistent.html")
        assert resp.status_code == 404
        assert "text/html" in resp.headers["Content-Type"]
        assert "Not Found" in resp.text
        assert resp.headers["Cache-Control"] == "public, max-age=300"

    def test_fallback_404_on_even_missing_fallback(self, static_dir: Path, tmp_path: Path) -> None:
        """When the fallback file itself is missing, a plain 404 is returned."""
        missing_fallback = tmp_path / "does_not_exist.html"
        app = FastAPI()
        app.mount(
            "/static/notebooks",
            NotebookStaticFiles(directory=static_dir, fallback_path=missing_fallback),
            name="notebooks",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/static/notebooks/nonexistent.html")
        assert resp.status_code == 404

    def test_existing_file_not_affected_by_fallback(
        self, static_dir: Path, client: TestClient
    ) -> None:
        (static_dir / "real.html").write_text("<html>real</html>")

        resp = client.get("/static/notebooks/real.html")
        assert resp.status_code == 200
        assert resp.text == "<html>real</html>"


class TestNotebookStaticFilesConstruction:
    def test_default_fallback_path(self, static_dir: Path) -> None:
        nsf = NotebookStaticFiles(directory=static_dir)
        assert nsf._fallback_path.name == "notebook_missing.html"

    def test_custom_fallback_path(self, static_dir: Path, fallback_file: Path) -> None:
        nsf = NotebookStaticFiles(directory=static_dir, fallback_path=fallback_file)
        assert nsf._fallback_path == fallback_file
