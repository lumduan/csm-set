# Public Mode Guide

This page explains the public-mode architecture: what it is, the data boundary rules, the 403 write-block contract, the owner workflow for refreshing public artefacts, switching modes, and the audit tests that enforce the boundary.

## What public mode is

Public mode (`CSM_PUBLIC_MODE=true`) is a read-only operating mode that serves pre-computed research artefacts without requiring any credentials, tvkit setup, or TradingView authentication. It is the default mode in `docker-compose.yml` and the published GHCR image.

In public mode:
- **All GET endpoints work** — `/api/v1/signals/latest`, `/api/v1/backtest/summary`, `/api/v1/portfolio/current`, `/static/notebooks/*`, etc.
- **All write endpoints are blocked** — any POST/PUT/PATCH/DELETE to `/api/v1/*` returns `403 Forbidden`.
- **No tvkit** — the `OHLCVLoader` is never instantiated; no TradingView credentials are needed.
- **No scheduler** — the APScheduler daily refresh job is not started.
- **Results are served from disk** — `results/static/` is mounted read-only in Docker; the API reads directly from committed JSON/HTML files.

## Data boundary rules

Public-mode data boundary is enforced at two layers:

### Layer 1 — File-level audit

`results/static/**/*.json` files must never contain raw OHLCV fields. The following keys are prohibited in any committed JSON:

- `open`, `high`, `low`, `close`, `volume`, `adj_close`

The audit runs as part of the test suite and blocks commit if any raw price field leaks into committed JSON. Only derived fields (NAV, z-score, quintile, rank percentile, CAGR, Sharpe, drawdown) may appear.

### Layer 2 — API-level audit

The `public_mode_guard` in `api/security.py` intercepts every request in public mode. Any non-GET method on `/api/v1/*` returns:

```json
{
  "detail": "Disabled in public mode"
}
```

Status code: **403 Forbidden**. Content type: `application/json`.

## 403 contract

The public-mode 403 response is canonical and stable. Any client can rely on:
- Status code `403` (not 401, which is reserved for auth failures)
- JSON body with `"detail": "Disabled in public mode"`
- No `request_id` in the body (unlike auth 401 responses)

The protected endpoints in public mode:
- `POST /api/v1/data/refresh`
- `POST /api/v1/backtest/run`
- `POST /api/v1/jobs`
- `POST /api/v1/scheduler/run/daily_refresh`
- Any other non-GET method on `/api/v1/*` (defence-in-depth via `is_protected_path()`)

The `docker-smoke.yml` CI workflow validates the 403 contract on every PR that touches Docker files — it POSTs to `/api/v1/data/refresh` and asserts a 403 response.

## Configuring API Key (Private Mode)

When running in private mode (`CSM_PUBLIC_MODE=false`), write endpoints are available but can be protected by an API key:

### Setting the key

```bash
# Generate a strong random key
python -c 'import secrets; print(secrets.token_urlsafe(32))'

# Set in .env
echo "CSM_API_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
```

Or in `docker-compose.private.yml`:
```yaml
environment:
  CSM_API_KEY: "your-generated-key-here"
```

### Sending the key

All requests to protected endpoints must include the `X-API-Key` header:

```bash
curl -H 'X-API-Key: your-key-here' http://localhost:8000/api/v1/data/refresh
```

### 401 response (missing or invalid key)

When `CSM_API_KEY` is set and a request to a protected endpoint lacks a valid key:

```json
{
  "type": "tag:csm-set,2026:problem/missing-api-key",
  "title": "Missing API key",
  "status": 401,
  "detail": "Missing X-API-Key header.",
  "instance": null,
  "request_id": "01JABCDEFGH1234567890"
}
```

The response:
- Uses `Content-Type: application/problem+json` (RFC 7807).
- Includes a `request_id` (ULID) for log correlation.
- Never echoes the supplied key.
- Uses `secrets.compare_digest()` for constant-time comparison (prevents timing side-channels).

### Key redaction

The configured API key is automatically redacted from all log output by `api.logging.install_key_redaction`. Even if a key appears in an error message or request log, it is replaced with `[REDACTED]`.

### Startup warning

If `CSM_PUBLIC_MODE=false` and `CSM_API_KEY` is not set, the server logs a WARNING at startup:

```
WARNING: Private mode active but CSM_API_KEY is not set. Protected endpoints are open.
```

This is intentional for local development but should never appear in production.

## Testing security paths

Auth and public-mode enforcement are tested in:
- `tests/integration/test_api_auth.py` — end-to-end auth tests with FastAPI TestClient
- `tests/unit/test_api_security.py` — unit tests for `is_protected_path()` and `APIKeyMiddleware`

To write a private-mode auth test:
```python
def test_protected_endpoint_requires_key(client):
    resp = client.post("/api/v1/data/refresh")
    assert resp.status_code == 401
    assert "Missing X-API-Key" in resp.json()["detail"]

def test_protected_endpoint_accepts_valid_key(client, monkeypatch):
    monkeypatch.setenv("CSM_API_KEY", "test-key")
    resp = client.post("/api/v1/data/refresh", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
```

To write a public-mode 403 test:
```python
def test_write_blocked_in_public_mode(client, monkeypatch):
    monkeypatch.setenv("CSM_PUBLIC_MODE", "true")
    resp = client.post("/api/v1/data/refresh")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Disabled in public mode"
```

## Owner workflow (end-to-end)

When you need to refresh the public research with new data:

### 1. Fetch live data
```bash
docker compose -f docker-compose.yml -f docker-compose.private.yml up -d
docker compose exec csm bash

# Inside the container:
uv run python scripts/fetch_history.py      # Pull OHLCV via tvkit
uv run python scripts/build_universe.py     # Build monthly snapshots
```

### 2. Generate research outputs
```bash
uv run python scripts/export_results.py     # Notebooks → HTML, backtest + signals → JSON
```

### 3. Verify the data boundary
```bash
uv run pytest tests/integration/test_public_data_boundary_* -v
```

### 4. Commit and release
```bash
exit  # Back on host

git add results/static/
git commit -m "results: refresh $(date +%Y-%m-%d)"
git push

# Tag a new version (triggers GHCR publish)
git tag v0.7.0
git push --tags
```

Public users get the updated research on their next `git pull` or `docker pull`.

## Audit tests

The data boundary is enforced by automated tests:

```bash
# Run all boundary audit tests
uv run pytest tests/integration/test_public_data_boundary_* -v

# Run a specific audit
uv run pytest tests/integration/test_public_data_boundary_json.py -v
```

These tests:
1. Recursively scan `results/static/**/*.json` for prohibited OHLCV keys.
2. Hit each public API endpoint and assert no `open`, `high`, `low`, `close`, `volume`, `adj_close` appear in the response JSON.
3. Assert the 403 contract on write endpoints in public mode.

## Switching modes

| From | To | How |
|------|----|-----|
| Public | Private | Set `CSM_PUBLIC_MODE=false` in `.env` or docker-compose override |
| Private | Public | Set `CSM_PUBLIC_MODE=true`; ensure `results/static/` is populated |

The runtime mode is logged at startup:
```
INFO: Running in public mode — write endpoints disabled
INFO: Running in private mode — write endpoints enabled
```

## Cross-references

- [Architecture Overview](../architecture/overview.md) § Public-mode boundary and § Security model
- [Docker Guide](../guides/docker.md) — public and private compose recipes
- [Getting Started](../getting-started/overview.md) — quickstart
- [api/security.py](../../api/security.py) — `public_mode_guard` and `APIKeyMiddleware` implementation
