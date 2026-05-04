# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No unreleased changes._

## [0.7.1] — 2026-05-04

### Changed

- **tvkit auth**: replaced `TVKIT_BROWSER` + Chrome-profile-mount authentication
  with a JSON cookie blob in the unprefixed `TVKIT_AUTH_TOKEN` env var. Works in
  CI/headless containers (no `browser_cookie3`, no host browser dependency).
  Operators must export `TVKIT_AUTH_TOKEN` (sessionid required; sessionid_sign,
  device_t, tv_ecuid recommended) — see
  [docs/guides/docker.md](docs/guides/docker.md#obtaining-tvkit_auth_token).
- `docker-compose.private.yml` now requires `TVKIT_AUTH_TOKEN` to be exported in
  the host shell (`${TVKIT_AUTH_TOKEN:?...}` fails fast if unset) and no longer
  mounts the host Chrome profile.

### Added

- `TradingViewCookies` Pydantic model (sessionid required, others optional,
  extras allowed) with JSON validation at `Settings()` construction time, so
  misconfiguration surfaces at startup instead of first fetch.
- `Settings.tvkit_cookies` property returning the parsed cookie model.
- Opt-in live integration test (`RUN_TVKIT_LIVE=1 uv run pytest
  tests/integration/test_tvkit_auth_live.py`) that hits TradingView and asserts
  >10,000 daily bars are returned for `NASDAQ:AAPL` with cookie auth (verified
  locally: 11,432 bars).

### Removed

- `Settings.tvkit_browser` field and all `TVKIT_BROWSER` references in compose,
  tests, and docs.
- Chrome profile volume mount from `docker-compose.private.yml`.

### Migration

- In your `.env` (or host shell), replace `TVKIT_BROWSER=chrome` with a single
  line `TVKIT_AUTH_TOKEN={"sessionid":"...", ...}` (extract cookies from your
  browser's DevTools → Application → Cookies → tradingview.com).
- If you used the private compose override, `export TVKIT_AUTH_TOKEN=...` in
  your shell before running `docker compose -f docker-compose.yml -f
  docker-compose.private.yml up`.

## [0.1.0] — pre-release scaffold

### Added

- Initial project scaffold: library core, API, UI, Docker setup
- Public mode architecture: pre-computed results served from `results/`
- Cross-sectional momentum research framework
- FastAPI backend with public mode middleware
- NiceGUI dashboard with regime detection, signal rankings, backtest viewer
- `scripts/export_results.py` for owner-side result generation
