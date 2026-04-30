"""Integration tests for notebook index and static file serving."""

from __future__ import annotations

from api.schemas.notebooks import NotebookIndex
from fastapi.testclient import TestClient


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
