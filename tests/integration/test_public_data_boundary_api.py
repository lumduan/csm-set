"""Data boundary audit — API response layer.

Boots a public-mode ``TestClient``, hits every read endpoint, and recursively
scans each JSON response for forbidden OHLCV field names.  Also asserts that
write endpoints return 403 with the canonical public-mode rejection body.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {"open", "high", "low", "close", "volume", "adj_close", "adjusted_close"}
)

# Read endpoints that must return 200 and contain zero OHLCV fields.
# /api/v1/universe is excluded — it reads from ParquetStore (private-mode only,
# no public JSON fallback) and returns 404 in public test client.
READ_ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/api/v1/signals/latest"),
    ("GET", "/api/v1/portfolio/current"),
    ("GET", "/api/v1/notebooks"),
    ("GET", "/health"),
]

# Write endpoints that must return 403 in public mode.
WRITE_ENDPOINTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("POST", "/api/v1/backtest/run", {"formation_months": 12, "skip_months": 1}),
    ("POST", "/api/v1/data/refresh", None),
    ("POST", "/api/v1/scheduler/run/daily_refresh", None),
    ("GET", "/api/v1/jobs", None),
]


# ---------------------------------------------------------------------------
# Recursive JSON scanner
# ---------------------------------------------------------------------------


def _scan_json_keys(obj: object, path: str = "$") -> Generator[tuple[str, str], None, None]:
    """Yield ``(json_path, forbidden_key)`` for any dict key matching a forbidden OHLCV name."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}"
            if key.lower() in FORBIDDEN_KEYS:
                yield child_path, key
            yield from _scan_json_keys(value, child_path)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            yield from _scan_json_keys(item, f"{path}[{idx}]")


def _assert_no_forbidden_keys(payload: object, endpoint: str) -> None:
    """Raise ``AssertionError`` if *payload* contains any OHLCV field name."""
    violations = list(_scan_json_keys(payload))
    if violations:
        msgs = "\n".join(f"  {path}: forbidden key '{key}'" for path, key in violations)
        pytest.fail(f"{endpoint}: {len(violations)} OHLCV key(s) in response:\n{msgs}")


# ---------------------------------------------------------------------------
# Read endpoint audit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method, path", READ_ENDPOINTS)
def test_read_endpoint_no_ohlcv(
    public_client: TestClient,
    tmp_results_signals_full: Path,
    tmp_results_portfolio_full: Path,
    tmp_results_notebooks_full: Path,
    method: str,
    path: str,
) -> None:
    """Every public read endpoint must return 200 with zero OHLCV keys in the response."""
    resp = public_client.request(method, path)
    assert resp.status_code == 200, (
        f"{method} {path} returned {resp.status_code}, expected 200: {resp.text[:500]}"
    )

    content_type = resp.headers.get("content-type", "")
    if "application/json" not in content_type:
        return  # non-JSON response (e.g. static HTML) — covered by file audit

    try:
        payload: object = resp.json()
    except ValueError:
        return  # not JSON

    _assert_no_forbidden_keys(payload, f"{method} {path}")


# ---------------------------------------------------------------------------
# Write endpoint 403 audit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method, path, body", WRITE_ENDPOINTS)
def test_write_endpoint_returns_403(
    public_client: TestClient,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    """Every write endpoint must return 403 in public mode."""
    if body is not None:
        resp = public_client.request(method, path, json=body)
    else:
        resp = public_client.request(method, path)
    assert resp.status_code == 403, (
        f"{method} {path} returned {resp.status_code}, expected 403: {resp.text[:500]}"
    )
    response_body = resp.json()
    assert "Disabled in public mode" in response_body.get("detail", ""), (
        f"{method} {path} 403 body missing canonical message: {resp.text[:500]}"
    )


# ---------------------------------------------------------------------------
# Deliberate-leak negative tests
# ---------------------------------------------------------------------------


def test_scanner_catches_deliberate_leak() -> None:
    """The recursive scanner must flag an object with a forbidden key."""
    payload: dict[str, object] = {
        "rankings": [
            {"symbol": "X", "z_score": 1.5, "close": 123.45},
        ]
    }
    violations = list(_scan_json_keys(payload))
    assert len(violations) == 1, f"Expected 1 violation, got {violations}"
    assert violations[0][1] == "close"


def test_scanner_catches_nested_leak() -> None:
    """Deeply nested forbidden keys must be found."""
    payload: dict[str, object] = {"results": {"metrics": {"derived": {"volume": 999999}}}}
    violations = list(_scan_json_keys(payload))
    assert len(violations) == 1, f"Expected 1 violation, got {violations}"
    assert violations[0][1] == "volume"


def test_scanner_passes_clean_data() -> None:
    """A clean payload must not trigger the scanner."""
    payload: dict[str, object] = {
        "rankings": [
            {"symbol": "X", "z_score": 1.5, "quintile": 3, "rank_pct": 0.75},
        ]
    }
    violations = list(_scan_json_keys(payload))
    assert len(violations) == 0


def test_deliberate_api_leak_detected(public_client: TestClient, tmp_results: Path) -> None:
    """If a committed results file contains OHLCV keys, the API audit must catch it."""
    leak_path = tmp_results / "signals" / "latest_ranking.json"
    leak_data = {
        "as_of": "2026-04-21",
        "rankings": [
            {"symbol": "X", "z_score": 1.5, "close": 123.45},
        ],
    }
    leak_path.write_text(json.dumps(leak_data))

    resp = public_client.get("/api/v1/signals/latest")
    assert resp.status_code == 200

    violations = list(_scan_json_keys(resp.json()))
    assert len(violations) >= 1, (
        f"Expected at least 1 OHLCV violation via API, got none. Response: {resp.text[:500]}"
    )
