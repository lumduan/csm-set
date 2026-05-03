# Docker Guide

This page covers Docker Compose recipes for public and private (owner) mode, healthcheck behaviour, CORS configuration, and troubleshooting.

## Table of Contents

- [Public boot](#public-boot)
- [Private boot (owner)](#private-boot-owner)
- [Pre-built image](#pre-built-image)
- [Healthcheck behaviour](#healthcheck-behaviour)
- [CORS configuration](#cors-configuration)
- [Troubleshooting](#troubleshooting)

---

## Public boot

The default mode. No credentials, no configuration.

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set
docker compose up
```

Open [http://localhost:8000](http://localhost:8000).

### What's baked in

| Setting | Value | Meaning |
|---------|-------|---------|
| `CSM_PUBLIC_MODE` | `true` | Read-only API; write endpoints return 403 |
| `CSM_LOG_LEVEL` | `INFO` | Standard log verbosity |
| `CSM_CORS_ALLOW_ORIGINS` | `*` | Open CORS — any origin can call the API |

### Mounts

| Host path | Container path | Mode | Purpose |
|-----------|---------------|------|---------|
| `./results` | `/app/results` | `:ro` (read-only) | Pre-computed research artefacts |

The image is built from the local `Dockerfile` (multi-stage: `python:3.11-slim` builder + runtime). The build step uses `uv` to install production dependencies.

### Stopping

```bash
docker compose down
```

---

## Private boot (owner)

For the project owner with tvkit credentials. Enables data fetching, write endpoints, and result regeneration.

```bash
docker compose -f docker-compose.yml -f docker-compose.private.yml up -d
```

Docker Compose merges the two files. The private override:

| Override | Value | Effect |
|----------|-------|--------|
| `CSM_PUBLIC_MODE` | `false` | Enable write endpoints and data fetches |
| `TVKIT_BROWSER` | `chrome` | Use Chrome for tvkit browser auth |
| `CSM_CORS_ALLOW_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Restrict CORS to local dev servers |
| `./data` mount | `/app/data` (rw) | Writable OHLCV data |
| `./results` mount | `/app/results` (rw) | Writable results |
| Chrome profile mount | `/root/.config/google-chrome` (`:ro`) | tvkit browser auth tokens |

### Owner workflow inside the container

```bash
# Enter the container
docker compose exec csm bash

# Fetch fresh OHLCV data
uv run python scripts/fetch_history.py

# Build universe snapshots
uv run python scripts/build_universe.py

# Export results (notebooks → HTML, backtest + signals → JSON)
uv run python scripts/export_results.py
exit
```

### After refreshing

On your host machine:

```bash
git add results/static/
git commit -m "results: refresh $(date +%Y-%m-%d)"
git push
```

Public users get the updated research on their next `git pull` or image rebuild.

### Securing private mode with an API key

When running in private mode, protect write endpoints with `CSM_API_KEY`:

```bash
# Generate a strong random key
python -c 'import secrets; print(secrets.token_urlsafe(32))'

# Add to docker-compose.private.yml environment:
#   CSM_API_KEY: "your-generated-key-here"
```

Without an API key, the lifespan emits a `WARNING` log but allows access (dev-mode pass-through). For any deployment exposed beyond loopback, set `CSM_API_KEY`.

Send requests with the key:

```bash
curl -H "X-API-Key: your-generated-key-here" \
  -X POST http://localhost:8000/api/v1/data/refresh
```

---

## Pre-built image

Skip the local build entirely:

```bash
docker pull ghcr.io/lumduan/csm-set:latest
docker run -p 8000:8000 ghcr.io/lumduan/csm-set:latest
```

Available tags:
- `latest` — most recent release
- `vX.Y.Z` — specific release (e.g., `v0.7.0`)
- `vX.Y` — minor version track (e.g., `v0.7`)
- `sha-<short-sha>` — specific commit

For the publishing workflow, see [RELEASING.md](../../RELEASING.md).

---

## Healthcheck behaviour

Both the Dockerfile and docker-compose.yml define the same healthcheck:

```
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `interval` | 30s | Check every 30 seconds |
| `timeout` | 5s | Mark unhealthy if the check takes > 5s |
| `start-period` | 20s | Grace period after container start before checks begin |
| `retries` | 3 | Consecutive failures before marking unhealthy |

Check the status:

```bash
docker compose ps
# Look for "(healthy)" in the STATUS column
```

---

## CORS configuration

### Public mode (default)

`CSM_CORS_ALLOW_ORIGINS=*` — any origin can call the API. Suitable for public-facing deployments and local experimentation.

### Private mode

Restrict to your development servers:

```yaml
# In docker-compose.private.yml
environment:
  CSM_CORS_ALLOW_ORIGINS: "http://localhost:3000,http://localhost:5173"
```

Example for a React dev server on port 3000:

```javascript
// From http://localhost:3000
const resp = await fetch('http://localhost:8000/api/v1/signals/latest');
const data = await resp.json();
```

Multiple origins are comma-separated. The middleware parses them from the `CSM_CORS_ALLOW_ORIGINS` env var.

---

## Troubleshooting

### Port 8000 already in use

**Symptom:** `docker compose up` fails with `Error starting userland proxy: listen tcp4 0.0.0.0:8000: bind: address already in use`.

**Fix:** Find and stop the process using port 8000:

```bash
lsof -ti:8000 | xargs kill
```

Or run csm-set on a different port:

```bash
CSM_PORT=8001 docker compose up
# Add to docker-compose.yml: ports: ["8001:8000"]
```

### Docker daemon not running

**Symptom:** `Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?`

**Fix:**
- **macOS:** Start Docker Desktop from `/Applications`.
- **Linux:** `sudo systemctl start docker` and ensure your user is in the `docker` group (`sudo usermod -aG docker $USER`).
- **Windows:** Start Docker Desktop from the Start menu.

### Container exits with OOM (out of memory)

**Symptom:** Container stops silently during `nbconvert` or backtest computation. `docker compose ps` shows `Exited (137)`.

**Fix:** The public compose file sets `mem_limit: 2g`. If you have many notebooks or a long backtest horizon, increase it:

```yaml
# In docker-compose.yml or a local override
services:
  csm:
    mem_limit: 4g
```

Or run export scripts locally where memory is unconstrained:

```bash
uv run python scripts/export_results.py
```

### Build fails: missing Python 3.11

**Symptom:** `docker compose up` fails at the build stage with `Unable to find image 'python:3.11-slim'`.

**Fix:** Ensure Docker is connected to the internet and can pull from Docker Hub. Run `docker pull python:3.11-slim` to test connectivity.

### Healthcheck fails

**Symptom:** Container status shows `(unhealthy)` even though the API seems to work.

**Fix:**
1. Check the health endpoint directly: `curl http://localhost:8000/health`
2. If it returns JSON, the issue may be transient — wait for the next check interval
3. If it hangs, the API may be stuck — check logs: `docker compose logs csm`
4. Common cause: `start_period` too short for slow machines; increase to 60s

### `uv sync` fails inside container

**Symptom:** `uv sync --frozen` fails with `No solution found when resolving dependencies`.

**Fix:** The `--frozen` flag means uv uses the exact versions in `uv.lock`. If you've modified `pyproject.toml` dependencies, update the lock file first:

```bash
uv lock
# Then rebuild
docker compose build --no-cache
```
