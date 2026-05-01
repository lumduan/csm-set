# Lessons Learned — csm-set

What worked, what didn't. Append; don't rewrite history.

## What Worked

- **Phase 1 (data pipeline) shipped on schedule** by keeping scope to: fetch → normalize → Parquet write. No premature feature creep.
- **Incremental Parquet writes (append by date partition)** beat full daily rewrites — orders of magnitude faster for end-of-day jobs.
- **Caching settfex calls** during research saved ~30 s per notebook run; cache invalidation tied to the trading day boundary.
- **Vectorized momentum calculation** beat row-wise `apply` by ~50× on full SET universe. Always benchmark before optimizing — but when the structure is row-wise iteration, the win is large.
- **Pydantic Settings for config** eliminated a class of "works on my machine" bugs by making the env contract explicit and validated at startup.
- **Notebook markdown in Thai** kept research artifacts accessible to the broader team without forcing a translation pass.

## What Didn't Work

- **Mocking pandas in tests** produced false greens that masked real DataFrame shape mismatches. Now: real small frames only.
- **Single mega-module `csm/core.py`** grew to 1.5k lines before being split. The split should have happened at ~400 lines. File-size budget now enforced.
- **APScheduler embedded in `api/`** caused state coupling and made the API non-stateless. Moved to `scripts/`. Don't repeat.
- **`requests` for "just one quick fetch"** in an async path — stalled the event loop. Now: `httpx.AsyncClient` is non-negotiable in `src/csm/` and `api/`.
- **Skipping the regression test "because the fix was obvious"** — bugs returned. Now: failing test first, every time.

## What's Still Unsettled

- Parquet partitioning strategy at the universe level — by date is good for read patterns, but cross-date queries are slower.
- Whether to introduce a metadata DB in `api/` for backtest run history (currently stored as JSON files).
- Whether to vendor or pin `tvkit` more tightly given upstream churn.

---

> **Append new lessons below. Date them. Be specific about the win or the loss.**
