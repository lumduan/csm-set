# Public Mode Guide

This page explains the public-mode architecture, data boundary rules, the 403 contract for write endpoints, the owner workflow for refreshing public-safe outputs, and how to configure API-key authentication for private mode.

## Table of Contents

- [What public mode is](#what-public-mode-is)
- [Data boundary rules](#data-boundary-rules)
- [403 contract](#403-contract)
- [Owner workflow](#owner-workflow)
- [Switching modes](#switching-modes)
- [Configuring API Key (Private Mode)](#configuring-api-key-private-mode)
- [Audit tests](#audit-tests)

---

## What public mode is

Public mode (`CSM_PUBLIC_MODE=true`) is the default operating mode of the csm-set Docker image. It is a **read-only safety mode** that:

1. Serves pre-computed research artefacts from `results/static/` — notebooks, backtest metrics, signal rankings
2. Exposes all GET endpoints under `/api/v1/` for programmatic consumption
3. Blocks all write endpoints with a 403 response
4. Disables all live data fetching — no tvkit calls, no TradingView credentials required
5. Disables the background scheduler — no automatic refreshes

Public mode is designed so that anyone who clones the repository can run `docker compose up` and get a fully functional API and dashboard with **zero configuration, zero credentials, and zero risk of leaking market data**.

### Public vs. private feature comparison

| Feature | Public mode | Private mode |
|---------|-------------|--------------|
| REST API (GET) | Full access | Full access |
| REST API (POST/PUT) | 403 — blocked | Enabled (auth required) |
| FastUI dashboard | Serves pre-computed data | Serves pre-computed + live data |
| Notebook HTML | Pre-rendered, committed to git | Can re-render from source |
| Live data fetch | Disabled | Enabled (tvkit + credentials) |
| Background scheduler | Disabled | Enabled (`CSM_REFRESH_CRON`) |
| CORS origins | `*` (open) | Restricted (configurable) |
| API-key auth | No-op | Enforced on protected paths |

---

## Data boundary rules

The public-mode data boundary prevents raw OHLCV (open, high, low, close, volume, adjusted close) from being distributed. This is enforced at three levels:

### 1. File system — `.gitignore`

The entire `data/` directory is gitignored. Raw Parquet files containing OHLCV data are never committed to the repository.

### 2. JSON artefacts — pre-commit audit

`results/static/` contains JSON files that are committed to git. These are audited by `tests/integration/test_public_data_boundary_files.py`, which scans every `.json` file under `results/static/` for OHLCV key patterns (`open`, `high`, `low`, `close`, `volume`, `adj_close`). Any match fails the test and blocks CI.

### 3. API responses — runtime audit

`tests/integration/test_public_data_boundary_api.py` hits every GET endpoint and asserts that no OHLCV keys appear in any response body. This ensures that even if raw data is loaded in private mode, it cannot leak through the API in public mode.

### What IS safe to distribute

- Processed outputs: CAGR, Sharpe ratio, Sortino ratio, max drawdown, win rate
- Signal rankings: symbol, sector, quintile, z-score, rank percentile
- Equity curves: NAV indexed to 100 (no raw prices)
- Notebook HTML: nbconvert output with code cells stripped
- All values derived from market data through aggregation, ranking, or statistical transformation

### What is NOT safe

- Raw OHLCV bars for any individual symbol at any frequency
- Any field named `open`, `high`, `low`, `close`, `volume`, or `adj_close` at the top level of a JSON file
- Any per-symbol time series that could be reverse-engineered to individual OHLCV bars

---

## 403 contract

In public mode, any request to a write endpoint returns a standard RFC 7807 problem detail response. The contract is:

### Protected endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/data/refresh` | POST | Trigger live OHLCV data refresh |
| `/api/v1/backtest/run` | POST | Run a fresh backtest |
| `/api/v1/jobs` | POST | Submit a background job |
| `/api/v1/scheduler/run/daily_refresh` | POST | Trigger the daily refresh job |

Additionally, any non-GET request to any `/api/v1/*` path is also blocked as defence-in-depth (in case new write endpoints are added without being added to the explicit set).

### 403 response shape

```json
{
  "type": "tag:csm-set,2026:problem/public-mode-disabled",
  "title": "Public mode — read only",
  "status": 403,
  "detail": "Disabled in public mode. Set CSM_PUBLIC_MODE=false to enable.",
  "instance": "/api/v1/data/refresh",
  "request_id": "01J..."
}
```

The `request_id` is a ULID that correlates with the server's access log for debugging. The `type` URI is a project-specific problem type tag.

### How to reproduce

```bash
# Start in public mode (default)
docker compose up -d

# Try to write — expect 403
curl -X POST http://localhost:8000/api/v1/data/refresh -i
# HTTP/1.1 403 Forbidden
# Content-Type: application/problem+json
```

---

## Owner workflow

The project owner (with tvkit credentials) refreshes public-safe outputs and commits them so public users always see up-to-date research.

### Step 1: Start in private mode

```bash
docker compose -f docker-compose.yml -f docker-compose.private.yml up -d
```

### Step 2: Fetch fresh data

```bash
docker compose exec csm uv run python scripts/fetch_history.py
```

This uses tvkit to pull OHLCV data from TradingView. Requires a valid tvkit setup with Chrome profile authentication.

### Step 3: Build universe

```bash
docker compose exec csm uv run python scripts/build_universe.py
```

Generates monthly universe snapshots under `data/processed/universe/`.

### Step 4: Export results

```bash
docker compose exec csm uv run python scripts/export_results.py
```

This runs all four notebooks through `nbconvert` (code cells stripped), generates backtest JSON + JSON Schema sidecars, and produces the latest signal ranking JSON. Output goes to `results/static/`.

### Step 5: Audit before committing

```bash
# Run the data boundary audit locally
uv run pytest tests/integration/test_public_data_boundary_*.py -v
```

### Step 6: Commit and publish

```bash
git add results/static/
git commit -m "results: refresh $(date +%Y-%m-%d)"
git push
```

### Step 7: Tag and publish the image (optional)

If the refresh coincides with a release:

```bash
git tag v0.7.0
git push --tags
# docker-publish.yml triggers automatically on the tag push
```

---

## Switching modes

### From public → private

Set `CSM_PUBLIC_MODE=false`:

```bash
# In .env
CSM_PUBLIC_MODE=false
CSM_API_KEY=<your-key>

# In docker-compose.private.yml (already set)
# environment:
#   CSM_PUBLIC_MODE: "false"
```

Restart the container. The API will now accept write requests (authenticated by `X-API-Key` if configured). The scheduler will start and run on the configured cron schedule.

### From private → public

Set `CSM_PUBLIC_MODE=true`. The container immediately:
- Returns 403 on all write endpoints
- Stops the scheduler
- Passes through all read requests

### Runtime check

The `public_mode_guard` in `api/main.py` checks `settings.public_mode` on every request. The `APIKeyMiddleware` in `api/security.py` also checks it — in public mode, the middleware is a complete no-op. Mode switching at runtime does not require a container restart (the `Settings` singleton reads env vars, which are fixed at container start in Docker, but local `uv run` picks up `.env` changes on restart).

---

## Configuring API Key (Private Mode)

When operating in private mode (`CSM_PUBLIC_MODE=false`), protect write endpoints with the `X-API-Key` header. The middleware lives in `api/security.py` and was shipped in Phase 5.7.

### Generating a key

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
# Output: dGhpcyBpcyBhIHNhbXBsZSBrZXkgZm9yIGRvY3VtZW50YXRpb24
```

### Setting the key

Add to `.env` or `docker-compose.private.yml`:

```bash
CSM_API_KEY=dGhpcyBpcyBhIHNhbXBsZSBrZXkgZm9yIGRvY3VtZW50YXRpb24
```

### Sending requests

```bash
curl -H "X-API-Key: dGhpcyBpcyBhIHNhbXBsZSBrZXkgZm9yIGRvY3VtZW50YXRpb24" \
  -X POST http://localhost:8000/api/v1/data/refresh
```

### Protected paths

The middleware protects these paths (defined in `api/security.py:PROTECTED_PATHS`):

- `/api/v1/data/refresh`
- `/api/v1/backtest/run`
- `/api/v1/jobs`
- `/api/v1/scheduler/run/daily_refresh`

As defence-in-depth, any non-GET request to `/api/v1/*` is also protected, even if not in the explicit set.

### Startup warning

If `CSM_PUBLIC_MODE=false` and `CSM_API_KEY` is not set, the lifespan emits a `WARNING`:

```
CSM_API_KEY is not configured; private-mode auth is DISABLED.
Set CSM_API_KEY before exposing this API beyond loopback.
```

This is a dev-mode convenience (no key needed on loopback), but for any non-loopback deployment, set the key.

### Auth error responses

**401 — missing header:**
```json
{
  "type": "tag:csm-set,2026:problem/missing-api-key",
  "title": "Missing API key",
  "status": 401,
  "detail": "Missing X-API-Key header.",
  "instance": null,
  "request_id": "01J..."
}
```

**401 — invalid key:**
```json
{
  "type": "tag:csm-set,2026:problem/invalid-api-key",
  "title": "Invalid API key",
  "status": 401,
  "detail": "Invalid X-API-Key header.",
  "instance": null,
  "request_id": "01J..."
}
```

Key observations:
- The response never echoes the supplied key
- Comparison is constant-time via `secrets.compare_digest` (prevents timing side-channel)
- The configured key is redacted in all log output via `api/logging.py:install_key_redaction`
- The `request_id` correlates with server logs for debugging

### Distinguishing 401 from 403

- **401** = private mode + missing or wrong `X-API-Key` → "authenticate first"
- **403** = public mode → "this endpoint is disabled globally, auth or not"

---

## Audit tests

The data boundary audit is a pair of integration tests that run in CI:

### File audit (`tests/integration/test_public_data_boundary_files.py`)

Scans every `.json` file under `results/static/` for OHLCV key patterns. Run it locally:

```bash
uv run pytest tests/integration/test_public_data_boundary_files.py -v
```

### API audit (`tests/integration/test_public_data_boundary_api.py`)

Hits every GET endpoint and asserts no OHLCV keys appear. Requires the API to be running:

```bash
# Start the API in public mode
uv run uvicorn api.main:app --port 8000 &

# Run the audit
uv run pytest tests/integration/test_public_data_boundary_api.py -v
```

Both tests are part of the CI quality gate and must pass before merge. If you add a new JSON artefact or API endpoint, update the audit tests accordingly.
