"""OpenAPI schema snapshot test.

Pins the generated OpenAPI JSON so intentional schema changes are
reviewable via ``git diff`` on the snapshot file.

Update procedure (when you *intend* to change the API schema)::

    uv run python -c "
    import json
    from pathlib import Path
    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as c:
        r = c.get('/openapi.json')
    Path('tests/integration/__snapshots__/openapi.json').write_text(
        json.dumps(r.json(), indent=2, sort_keys=True) + '\n'
    )
    "

Commit the updated snapshot alongside the schema change.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

SNAPSHOT = Path(__file__).parent / "__snapshots__" / "openapi.json"


def _normalize(schema: dict) -> dict:
    """Normalize an OpenAPI dict for stable comparison."""
    return json.loads(json.dumps(schema, indent=2, sort_keys=True))


def test_openapi_schema_matches_snapshot(client: TestClient) -> None:
    """The generated /openapi.json must match the pinned snapshot."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    generated = _normalize(resp.json())
    snapshot = _normalize(json.loads(SNAPSHOT.read_text()))
    assert generated == snapshot, (
        "OpenAPI schema differs from snapshot. "
        "If this is intentional, update the snapshot per the docstring."
    )


def test_openapi_json_content_type(client: TestClient) -> None:
    """OpenAPI JSON endpoint returns correct content type."""
    resp = client.get("/openapi.json")
    assert "application/json" in resp.headers.get("content-type", "")


def test_openapi_info_has_version_from_csm(client: TestClient) -> None:
    """The OpenAPI info.version matches csm.__version__."""
    from csm import __version__

    resp = client.get("/openapi.json")
    assert resp.json()["info"]["version"] == __version__


def test_every_route_has_summary_and_response_model(client: TestClient) -> None:
    """Every non-documentation route must declare summary, description, and response_model."""
    resp = client.get("/openapi.json")
    schema = resp.json()
    missing: list[str] = []

    for path, methods in schema.get("paths", {}).items():
        for method, operation in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            label = f"{method.upper()} {path}"
            if not operation.get("summary"):
                missing.append(f"{label}: missing summary")
            if not operation.get("description"):
                missing.append(f"{label}: missing description")
            # 304 responses legitimately have no content schema, skip those
            resp_200 = operation.get("responses", {}).get("200", {})
            if resp_200 and not resp_200.get("content"):
                missing.append(f"{label}: missing response_model / content schema on 200")

    assert not missing, (
        f"{len(missing)} route(s) have incomplete OpenAPI metadata:\n"
        + "\n".join(f"  - {m}" for m in missing)
    )
