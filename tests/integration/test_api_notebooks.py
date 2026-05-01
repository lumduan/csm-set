"""Integration tests for notebook index and static file serving."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.schemas.notebooks import NotebookIndex


class TestNotebookIndexPublic:
    def test_index_returns_200(self, tmp_results_notebooks_full, public_client: TestClient) -> None:
        resp = public_client.get("/api/v1/notebooks")
        assert resp.status_code == 200

    def test_index_response_schema(
        self, tmp_results_notebooks_full, public_client: TestClient
    ) -> None:
        resp = public_client.get("/api/v1/notebooks")
        parsed = NotebookIndex(**resp.json())
        assert len(parsed.items) == 2

    def test_index_entries_have_required_fields(
        self, tmp_results_notebooks_full, public_client: TestClient
    ) -> None:
        resp = public_client.get("/api/v1/notebooks")
        data = resp.json()
        for item in data["items"]:
            assert "name" in item
            assert "path" in item
            assert "size_bytes" in item
            assert "last_modified" in item
            assert item["path"].startswith("/static/notebooks/")

    def test_index_empty_when_no_html(self, public_client: TestClient) -> None:
        resp = public_client.get("/api/v1/notebooks")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_index_empty_when_dir_missing(
        self, tmp_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the notebooks directory does not exist, the index returns empty."""
        import sys

        from csm.config.settings import Settings

        # Create a results dir without a notebooks subdirectory
        results = tmp_path / "results-no-notebooks"
        results.mkdir(parents=True)
        (results / ".tmp" / "jobs").mkdir(parents=True, exist_ok=True)

        monkeypatch.setenv("CSM_PUBLIC_MODE", "true")
        monkeypatch.setenv("CSM_RESULTS_DIR", str(results))
        monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))

        _settings_mod = sys.modules["csm.config.settings"]
        _original = _settings_mod.settings
        _settings_mod.settings = Settings()

        import api.deps as _api_deps
        import api.main as _api_main

        _orig_deps = _api_deps.settings
        _orig_main = _api_main.settings
        _api_deps.settings = _settings_mod.settings
        _api_main.settings = _settings_mod.settings
        try:
            from fastapi.testclient import TestClient

            from api.deps import set_store
            from csm.data.store import ParquetStore

            set_store(ParquetStore(tmp_path / "data" / "processed"))
            with TestClient(_api_main.app) as test_client:
                resp = test_client.get("/api/v1/notebooks")
                assert resp.status_code == 200
                assert resp.json()["items"] == []
        finally:
            _api_deps.settings = _orig_deps
            _api_main.settings = _orig_main
            _settings_mod.settings = _original

    def test_index_lists_only_html_files(self, tmp_results: str, public_client: TestClient) -> None:
        """Non-HTML files in the notebooks dir should be ignored by the index."""
        # tmp_results_notebooks_full fixture writes .html files.
        # Write a non-HTML file manually and verify it's excluded.
        from pathlib import Path

        (Path(tmp_results) / "notebooks" / "notes.txt").write_text("not html")
        resp = public_client.get("/api/v1/notebooks")
        names = [item["name"] for item in resp.json()["items"]]
        assert "notes.txt" not in names


class TestNotebookIndexETag:
    def test_etag_header_present(
        self, tmp_results_notebooks_full, public_client: TestClient
    ) -> None:
        resp = public_client.get("/api/v1/notebooks")
        assert "ETag" in resp.headers
        assert resp.headers["ETag"].startswith('W/"')

    def test_etag_304_roundtrip(
        self, tmp_results_notebooks_full, public_client: TestClient
    ) -> None:
        resp1 = public_client.get("/api/v1/notebooks")
        assert resp1.status_code == 200
        etag: str = resp1.headers["ETag"]

        resp2 = public_client.get(
            "/api/v1/notebooks",
            headers={"If-None-Match": etag},
        )
        assert resp2.status_code == 304

    def test_etag_stale_returns_200(
        self, tmp_results_notebooks_full, public_client: TestClient
    ) -> None:
        resp = public_client.get(
            "/api/v1/notebooks",
            headers={"If-None-Match": 'W/"stale-etag"'},
        )
        assert resp.status_code == 200

    def test_etag_consistent_for_same_data(
        self, tmp_results_notebooks_full, public_client: TestClient
    ) -> None:
        etag1 = public_client.get("/api/v1/notebooks").headers["ETag"]
        etag2 = public_client.get("/api/v1/notebooks").headers["ETag"]
        assert etag1 == etag2


class TestStaticNotebookFiles:
    def test_existing_notebook_served(
        self, tmp_results_notebooks_full, public_client: TestClient
    ) -> None:
        resp = public_client.get("/static/notebooks/01_test.html")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["Content-Type"]
        assert "01_test.html" in resp.text

    def test_cache_control_on_static_file(
        self, tmp_results_notebooks_full, public_client: TestClient
    ) -> None:
        resp = public_client.get("/static/notebooks/01_test.html")
        assert resp.headers["Cache-Control"] == "public, max-age=300"

    def test_missing_notebook_returns_fallback(self, public_client: TestClient) -> None:
        resp = public_client.get("/static/notebooks/nonexistent.html")
        assert resp.status_code == 404
        assert "text/html" in resp.headers["Content-Type"]
        assert "Notebook Not Found" in resp.text

    def test_fallback_has_cache_control(self, public_client: TestClient) -> None:
        resp = public_client.get("/static/notebooks/nonexistent.html")
        assert resp.status_code == 404
        assert resp.headers["Cache-Control"] == "public, max-age=300"

    def test_static_file_304_etag(
        self, tmp_results_notebooks_full, public_client: TestClient
    ) -> None:
        resp1 = public_client.get("/static/notebooks/01_test.html")
        etag: str = resp1.headers["ETag"]
        assert resp1.status_code == 200

        resp2 = public_client.get(
            "/static/notebooks/01_test.html",
            headers={"If-None-Match": etag},
        )
        assert resp2.status_code == 304
