# Docker Guide

How to run csm-set with Docker in public and private modes, configure CORS, understand the healthcheck, and troubleshoot common issues.

## Public boot (no credentials)

Start the container in public read-only mode — serves pre-computed research artefacts, no tvkit credentials needed:

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set
docker compose up
```

What happens:
- Builds the multi-stage Docker image (`Dockerfile`): builder stage installs dependencies, runtime stage is a slim Python 3.11 image.
- Starts uvicorn on port 8000 with `CSM_PUBLIC_MODE=true`.
- Mounts `results/` as read-only — public users can read static artefacts but cannot overwrite them.
- Healthcheck runs every 30s (`curl http://localhost:8000/health`) with 3 retries and a 20s start period.
- Memory limit: 2 GB.

## Private boot (requires tvkit credentials)

For owners who need to fetch live data, re-run notebooks, or regenerate backtest results:

```bash
cp .env.example .env
# Edit .env: set CSM_PUBLIC_MODE=false, add tvkit credentials

docker compose -f docker-compose.yml -f docker-compose.private.yml up -d
```

What the private override does:
- Mounts `data/` (writable) — raw and processed Parquet files.
- Mounts `results/` (writable) — allows updating static artefacts.
- Mounts `~/.config/google-chrome` (optional) — tvkit browser profile for TradingView auth.
- Mounts `.env` as environment variables.
- Sets `CSM_PUBLIC_MODE=false` — enables write endpoints, tvkit data fetching, and scheduler jobs.

## Pre-built image

Skip the build step with the published GHCR image:

```bash
docker pull ghcr.io/lumduan/csm-set:latest
docker run -p 8000:8000 ghcr.io/lumduan/csm-set:latest
```

Available tags:
- `latest` — most recent release
- `vX.Y.Z` — specific version
- `vX.Y` — minor version (latest patch)
- `sha-<short-sha>` — specific commit

The image is built and pushed automatically by `.github/workflows/docker-publish.yml` on every version tag (`v*.*.*`) push.

## Healthcheck behaviour

The container includes a Docker healthcheck:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 20s
```

- **Interval**: 30s between checks.
- **Timeout**: 10s per check.
- **Retries**: 3 failures → container marked unhealthy.
- **Start period**: 20s grace period after container start before checks begin.

In `docker compose up`, the `--wait` flag blocks until the healthcheck passes.

## CORS configuration

CORS origins are controlled by the `CSM_CORS_ALLOW_ORIGINS` environment variable (comma-separated):

| Mode | Default | Example override |
|------|---------|-----------------|
| Public | `*` (all origins allowed) | No override needed |
| Private | `*` (permissive) | `CSM_CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:5173` |

Set via `docker-compose.private.yml`:
```yaml
environment:
  CSM_CORS_ALLOW_ORIGINS: "http://localhost:3000,http://localhost:5173"
```

## Troubleshooting

| Symptom | Resolution |
|---------|------------|
| `Bind for 0.0.0.0:8000 failed: port is already allocated` | Another process is using port 8000. Find it: `lsof -i :8000`. Stop it, or use a different host port in an override compose file. |
| `Cannot connect to the Docker daemon` | Docker Desktop is not running. Start Docker Desktop and wait for the engine to be ready. |
| Container exits `137` (OOM) during build | The nbconvert step during image build exceeded the 2 GB memory limit. Increase Docker's memory allocation: Docker Desktop → Settings → Resources → Memory → at least 4 GB. |
| `Error response from daemon: pull access denied` | The GHCR image is private. Make sure you're authenticated: `echo $GITHUB_TOKEN | docker login ghcr.io -u YOUR_USERNAME --password-stdin`. |
| Container starts but `/health` returns 502 | Uvicorn hasn't finished booting. Wait for the healthcheck start period (20s). Check logs: `docker compose logs csm`. |
| `403` on write endpoints in private mode | `CSM_PUBLIC_MODE` is still `true`. Check your `.env` or docker-compose override: `echo $CSM_PUBLIC_MODE`. |
| `401` on write endpoints with API key set | You're not sending the `X-API-Key` header, or the key doesn't match. Check `CSM_API_KEY` in your env. Use `curl -H 'X-API-Key: <key>' ...`. |
| Mounted `data/` directory is empty or read-only | The host directory may not exist or have wrong permissions. Create it: `mkdir -p data/`, then `chmod 777 data/` (or `chown` to the container user). |

## Cross-references

- [Getting Started](../getting-started/overview.md) — public quickstart
- [Public Mode Guide](../guides/public-mode.md) — data boundary, 403 contract, owner workflow
- [Architecture Overview](../architecture/overview.md) — container architecture and data flow
