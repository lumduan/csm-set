# Recurring Bugs — csm-set

Bugs that have appeared more than once. Each entry: **Symptom → Root cause → Fix → Prevention test**. Append new entries; never silently delete history.

---

## 1. Symbol mismatch (settfex vs Yahoo / TradingView)

- **Symptom**: signals or backtests miss data, return NaN-only series, or join produces empty frames.
- **Root cause**: SET tickers exist in different conventions across sources (`PTT` vs `PTT.BK` vs `SET:PTT`). One source returns one form, another returns a different form, joins silently drop unmatched.
- **Fix**: normalize at ingestion via `settfex`'s canonical form; never compare raw strings from two different sources.
- **Prevention**: assertion test in `tests/data/test_symbol_normalization.py` covering each source's input → canonical form mapping.

---

## 2. Tz-naive vs tz-aware Timestamps in joins

- **Symptom**: `TypeError: Cannot compare tz-naive and tz-aware datetime-like` or, worse, a silent off-by-one-day join.
- **Root cause**: ingestion path returned tz-naive `Timestamp`, downstream code expected tz-aware (or vice versa).
- **Fix**: normalize at the data ingestion boundary to tz-aware UTC; convert to `Asia/Bangkok` only at presentation.
- **Prevention**: assertion `assert df.index.tz is not None` at every public function entry that takes a time-indexed frame.

---

## 3. Async fixture leakage in pytest

- **Symptom**: tests pass individually, fail when run together; "event loop closed" or hanging tests.
- **Root cause**: async fixtures with wrong scope, or missing `asyncio_mode = "auto"` in pytest config.
- **Fix**: configure `[tool.pytest.ini_options] asyncio_mode = "auto"` once; scope async fixtures to `function` unless deliberately broader.
- **Prevention**: CI runs the suite twice in different orders (`-p no:randomly` + `--randomly-seed=...`).

---

## 4. Empty DataFrame propagating NaN signals

- **Symptom**: portfolio gets all-NaN weights → backtest returns 0 P&L silently.
- **Root cause**: signal function called with empty / all-NaN price frame; downstream had no guard.
- **Fix**: guard at the entry of every public signal function — raise `ValueError` for empty input, or return a typed empty result with a logged warning.
- **Prevention**: `tests/signals/test_empty_inputs.py` covers every public signal function with empty / NaN-only inputs.

---

## 5. Sync `requests` snuck into async path

- **Symptom**: event loop stalls; latency spikes; healthcheck times out under load.
- **Root cause**: a transitive dependency or a quick "fix" pulled in `requests` and called it from `async def`.
- **Fix**: use `httpx.AsyncClient`; replace any `requests` import.
- **Prevention**: ruff rule (or grep in pre-commit) banning `import requests` under `src/csm/` and `api/`.

---

## 6. Parquet read without column pruning

- **Symptom**: memory spikes, slow reads on backtest startup.
- **Root cause**: `pq.read_table(path)` with no `columns=` argument loaded entire wide frames.
- **Fix**: always pass `columns=[...]` and `filters=[...]` where partitions exist.
- **Prevention**: code review checklist; benchmark in `scripts/bench_io.py` regression-tested.

---

> **Add new entries below this line. Format: heading → Symptom → Root cause → Fix → Prevention.**
