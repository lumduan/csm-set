# Releasing

How to cut a new csm-set release and publish the Docker image to GHCR.

## Prerequisites

- Write access to [lumduan/csm-set](https://github.com/lumduan/csm-set)
- Git configured locally
- (Optional) Docker installed to verify the published image

## Step-by-step

### 1. Ensure main is green

The `docker-smoke.yml` workflow must pass on `main`. Check the [Actions tab](https://github.com/lumduan/csm-set/actions/workflows/docker-smoke.yml).

### 2. Create an annotated tag

```bash
git checkout main
git pull origin main
git tag -a v0.6.0 -m "Phase 6: Docker & Public Distribution"
git push origin v0.6.0
```

Use [semver](https://semver.org/): `vMAJOR.MINOR.PATCH`. Annotated tags (`-a`) are preferred — the message shows up in the GitHub Releases UI.

### 3. Wait for the publish workflow

Pushing the tag triggers `.github/workflows/docker-publish.yml`. Monitor the run at [Actions > Docker Publish](https://github.com/lumduan/csm-set/actions/workflows/docker-publish.yml).

The workflow:
- Authenticates to `ghcr.io` via the built-in `GITHUB_TOKEN`
- Computes tags: `vX.Y.Z`, `vX.Y`, `latest` (highest semver), `sha-<short-sha>`
- Builds and pushes the image to `ghcr.io/lumduan/csm-set`

### 4. Verify the published image

```bash
docker pull ghcr.io/lumduan/csm-set:v0.6.0
docker run --rm -p 8000:8000 ghcr.io/lumduan/csm-set:v0.6.0
# Open http://localhost:8000 — dashboard should load
# curl http://localhost:8000/health should return 200
```

Also verify `latest` and the short-sha tag:

```bash
docker pull ghcr.io/lumduan/csm-set:latest
docker pull ghcr.io/lumduan/csm-set:sha-$(git rev-parse --short HEAD)
```

### 5. Create a GitHub Release (optional)

Go to [GitHub Releases](https://github.com/lumduan/csm-set/releases), select the tag, and write release notes summarizing the changes.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Workflow not triggering after `git push` | Verify the tag matches `v*.*.*` (e.g. `v0.6.0`); check `git tag -l` |
| `403 Forbidden` on push to GHCR | Ensure the workflow has `permissions: packages: write` |
| Image not visible at `ghcr.io/lumduan/csm-set` | Go to **Packages** → **csm-set** → **Package settings** → **Change visibility** → **Public** |
| `docker pull` returns `unauthorized` | The package is private; make it public (see above) or `docker login ghcr.io` first |
