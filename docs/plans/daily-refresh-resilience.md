# Daily Refresh Resilience (A+C)

## Why

The 18:00 BKK `daily_refresh` job intermittently loses a large fraction of the
TradingView fetch in a single burst — most recently 73/136 symbols on
2026-05-25, including 4 of the 9 held positions. The failure signature is
identical across all affected symbols: `received 1000 (OK); then sent 1000
(OK)` — an upstream WebSocket close, not a bug here. `OHLCVLoader.fetch`
already retries 3× per symbol on transient errors via `tvkit_retry_attempts`,
but every retry happens inside the same high-contention burst, so once
TradingView starts cycling connections all retries die together.

Held-symbol price gaps cascade: `compute_live_portfolio_metrics()` returns
`None`, `run_post_refresh_hook()` correctly **skips the gateway POST**, and the
live-test report / dashboard NAV don't update until somebody manually re-fires
`POST /api/v1/scheduler/run/daily_refresh` (yesterday's recovery: 20:22 BKK,
job `01KSFMV4B9W8HWMSAFYM8CYY4E`, clean run on the second attempt).

This change implements two complementary fixes:

- **A — outer-loop retry.** When `fetch_batch` returns with missing symbols,
  wait and re-fetch *only* the failed subset. Multiple attempts spaced by
  exponential backoff (with jitter) let TradingView's connection pool recover
  between bursts.
- **C — held-symbols-first.** Fetch the ~9 positions from
  `configs/live_portfolio.yaml` in their own clean batch *before* the
  universe sweep, with a stricter retry policy. Even on a partial universe
  failure, NAV reconstruction + gateway POST still succeed.

Outcome: the next time TradingView throttles us, the job self-recovers without
a human retrigger, and a partial universe failure no longer blocks the daily
report.

## Design

### Where the change lands

Single function: `daily_refresh()` in `api/scheduler/jobs.py`. All other
callers — `scripts/refresh_daily.py`, the `POST /api/v1/scheduler/run/...`
router — go through it unchanged.

### New flow inside `daily_refresh`

```
1. Load universe symbols from store (unchanged).
2. Load configs/live_portfolio.yaml via load_live_portfolio() if present.
3. Compute held_symbols by stripping any "SET:" prefix from each LivePosition.
4. Phase 1 — HELD batch (skipped if held_symbols empty / config missing):
      held_prices = await _fetch_batch_with_retry(
          loader, held_symbols,
          max_attempts=settings.refresh_held_max_attempts,    # default 4
          base_delay_secs=settings.refresh_retry_delay_secs,  # default 60
      )
      Log loudly if any held symbol still missing after retries.
5. Phase 2 — UNIVERSE batch (excludes held_symbols, no duplicate fetch):
      universe_prices = await _fetch_batch_with_retry(
          loader, [s for s in universe if s not in held_symbols],
          max_attempts=settings.refresh_universe_max_attempts,  # default 3
          base_delay_secs=settings.refresh_retry_delay_secs,
      )
6. fetched = {**universe_prices, **held_prices}   # held wins on overlap
7. Persist prices_latest (unchanged).
8. Build features (unchanged).
9. Post-refresh hook (unchanged).
10. Write marker file with extended fields (see below).
```

### `_fetch_batch_with_retry` helper

New module-level coroutine in `api/scheduler/jobs.py`:

```python
async def _fetch_batch_with_retry(
    loader: OHLCVLoader,
    symbols: list[str],
    *,
    max_attempts: int,
    base_delay_secs: int,
    interval: str = "1D",
    bars: int = 600,
) -> tuple[dict[str, pd.DataFrame], int]:
    """Call loader.fetch_batch and retry the FAILED subset with backoff.

    Returns (merged_fetched, retries_used). Each retry waits
    base_delay_secs * 2 ** (retry_index) seconds with ±20% jitter
    (lets TradingView's connection pool recover between bursts).
    """
```

- Exponential backoff: `delay = base * 2 ** retry_index` with ±20% jitter.
  Defaults give 60s → 120s → 240s.
- Each retry logs `attempt`, `requested`, `recovered`, `still_failing` at INFO.
- Returns the merged dict + a count of retries that actually fired (0 on the
  happy path); the count is summed across both phases for the marker file.

### New settings

Added to `src/csm/config/settings.py` alongside the existing `tvkit_*` fields:

| Env var | Attr | Default | Purpose |
|---|---|---|---|
| `CSM_REFRESH_HELD_MAX_ATTEMPTS` | `refresh_held_max_attempts: int` | `4` | Outer-loop batch attempts for held symbols |
| `CSM_REFRESH_UNIVERSE_MAX_ATTEMPTS` | `refresh_universe_max_attempts: int` | `3` | Outer-loop batch attempts for universe sweep |
| `CSM_REFRESH_RETRY_DELAY_SECS` | `refresh_retry_delay_secs: int` | `60` | Base backoff seconds (doubled each retry) |

Worst-case job runtime ≈ 16 min (held: 3 × ~70s fetch + 60+120+240s waits ≈ 630s;
universe: 2 × ~70s + 60+120s ≈ 320s), comfortably under the existing
`grace_time=3600`.

### Marker file (`results/.tmp/last_refresh.json`)

Existing keys (`timestamp`, `symbols_fetched`, `duration_seconds`, `failures`)
are preserved verbatim so the daily-log skill that reads this file keeps
working. Three new keys are added:

```json
{
  "timestamp": "...",
  "symbols_fetched": 136,
  "duration_seconds": 215.4,
  "failures": 0,
  "held_symbols_fetched": 9,
  "held_symbols_failed": 0,
  "retry_attempts_used": 1
}
```

`retry_attempts_used` = total outer-loop retries fired across both phases
(0 on the happy path). Useful telemetry for spotting silent degradation
before it turns into an outright failure.

### Held-symbol extraction

`LivePosition.symbol` may be bare (`DELTA`) or prefixed (`SET:DELTA`); the
universe parquet stores bare symbols. Strip the prefix when building the
held list:

```python
held_symbols = sorted({pos.symbol.split(":", 1)[-1] for pos in config.positions})
```

### Public-mode behaviour

`create_scheduler()` already returns `None` in public mode, so the scheduled
path isn't reachable. Public deployments typically have no
`configs/live_portfolio.yaml`, so the held phase is skipped and the universe
phase runs (with retry — same coverage as today, plus self-healing).

## Files modified

| File | Change |
|---|---|
| `api/scheduler/jobs.py` | Add `_fetch_batch_with_retry`; restructure `daily_refresh()` into held + universe phases; extend marker write |
| `src/csm/config/settings.py` | Add three new settings (defaults above) |
| `tests/unit/test_scheduler_jobs.py` | Add five unit tests (see below) |

No changes to: `OHLCVLoader` (its per-symbol retry stays), `ParquetStore`,
`run_post_refresh_hook`, `load_live_portfolio`, any router, any Docker file,
or the gateway ingestion contract.

## Tests added

1. **`test_daily_refresh_retries_failed_symbols`** — `fetch_batch` fails 3
   symbols on attempt 1, recovers them on attempt 2. Assert `failures == 0`
   and `retry_attempts_used == 1`. `asyncio.sleep` patched to a no-op for
   speed.
2. **`test_daily_refresh_fetches_held_symbols_first`** — write a fake
   `live_portfolio.yaml` with two held positions; record `fetch_batch` call
   order; assert held call precedes universe call and universe call's
   symbols exclude held names.
3. **`test_daily_refresh_held_failure_still_runs_universe`** — held batch
   exhausts retries with one symbol still missing; assert universe phase
   still runs, marker file records `held_symbols_failed == 1`, hook is still
   invoked.
4. **`test_daily_refresh_no_live_portfolio_config`** — config absent; assert
   held phase is skipped and a single universe `fetch_batch` runs
   (backwards-compat for public mode / any env without the YAML).
5. **`test_marker_file_extended_fields`** — assert the JSON contains the
   three new keys *and* preserves the four original keys with the same
   names.

Coverage stays ≥ 90% on `api/` (the existing quality gate).

## Verification

```bash
# 1. Quality gate
uv run ruff check . && uv run ruff format --check . \
  && uv run mypy src/ && uv run pytest tests/ -v

# 2. Manual smoke (private mode, host)
uv run python scripts/refresh_daily.py
cat results/.tmp/last_refresh.json   # new keys present, failures == 0

# 3. Manual smoke (container, the scheduled path)
docker compose -f docker-compose.yml -f docker-compose.private.yml up -d
curl -X POST -H "X-API-Key: $CSM_API_KEY" \
  http://localhost:8100/api/v1/scheduler/run/daily_refresh
docker exec csm-set-csm-1 cat /app/results/.tmp/last_refresh.json
```

Acceptance:
- Quality gate passes.
- Clean run: marker shows `held_symbols_failed == 0`, `retry_attempts_used == 0`.
- Simulated partial failure (test #1): recovers in attempt 2, no manual retrigger.
- Held-symbol total failure (test #3): job does not crash; universe and hook
  still run.

## Out of scope

- Watchdog cron (option B from the suggestion menu) — defer; revisit only if
  A+C prove insufficient after a few weeks of live observation.
- Chunking / pacing the fetch (option D) — premature without empirical data
  on TradingView's actual limits.
- Failover to settfex — separate, larger piece of work.
- Changes to `OHLCVLoader.fetch` per-symbol retry semantics.
- Any change to the gateway ingestion contract or `extended_data` shape.
