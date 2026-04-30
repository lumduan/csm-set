# Anti-Patterns — csm-set

Things to **avoid** in this repo. Each entry: the bad pattern → why → the right way.

---

## `requests` in async code

- **Bad**: `import requests; r = requests.get(url)` inside an `async def`.
- **Why**: blocks the event loop; degrades throughput across the whole service.
- **Right**: `async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as c: r = await c.get(url)`.

---

## Row-wise `pd.DataFrame.apply` / `iterrows` on hot paths

- **Bad**: `df.apply(lambda row: row.a * row.b, axis=1)` over a 100k-row frame.
- **Why**: 10-100× slower than vectorized ops; allocates a Python object per row.
- **Right**: `df["c"] = df["a"] * df["b"]` (or `np.where`, `df.eval`, `groupby.transform`).

---

## Hidden global config inside modules

- **Bad**: `from csm.config import GLOBAL; GLOBAL["timezone"] = "UTC"`.
- **Why**: action-at-a-distance; hides dependencies; breaks tests.
- **Right**: `pydantic-settings` `Settings()` instance loaded once at startup, passed down explicitly.

---

## Mocking pandas / numpy / pyarrow

- **Bad**: `mock.patch("pandas.DataFrame")` to "fake" a frame in a test.
- **Why**: tests pass while production breaks on real shape, dtype, or index issues.
- **Right**: build a small real frame in the test (`pd.DataFrame({"a": [1, 2], "b": [3, 4]})`).

---

## Bare `except:` and `except Exception: pass`

- **Bad**: `try: x() except: pass`.
- **Why**: hides bugs, hides keyboard interrupt, makes debugging impossible.
- **Right**: catch the narrowest type that captures the failure, log + re-raise or convert to a domain exception.

---

## Notebook code copy-pasted into `src/csm/`

- **Bad**: lifting a 200-line notebook cell into a module without restructuring.
- **Why**: notebook code is exploratory — mutable globals, side effects, no types, no tests.
- **Right**: refactor into typed functions with docstrings and tests; the notebook keeps the narrative, the module keeps the logic.

---

## `print` in `src/csm/`

- **Bad**: `print(f"got {n} rows")` left in committed code.
- **Why**: bypasses log levels, no structure, can't be filtered or routed.
- **Right**: `logger = logging.getLogger(__name__); logger.info("got %d rows", n)`.

---

## Returning bare `dict` from a FastAPI route

- **Bad**: `@app.get("/portfolio") def get(): return {"weights": {...}}`.
- **Why**: no schema validation, no OpenAPI accuracy, easy to drift between versions.
- **Right**: define a Pydantic response model, declare `response_model=Portfolio`, return the model instance.

---

## Hard-coded paths

- **Bad**: `pd.read_parquet("/Users/sarat/Code/csm-set/data/prices.parquet")`.
- **Why**: breaks on every other machine and in CI.
- **Right**: paths come from `Settings()` (a `DATA_DIR` env var, defaulting to a project-relative path).

---

## Mixing tz-naive and tz-aware Timestamps

- **Bad**: `df.index = pd.to_datetime(df["date"])` with no tz.
- **Why**: silently wrong joins; off-by-one-day P&L bugs.
- **Right**: `df.index = pd.to_datetime(df["date"]).tz_localize("Asia/Bangkok").tz_convert("UTC")` at ingestion.

---

## Optimizing without a benchmark

- **Bad**: rewriting code for "speed" because it "looks slow".
- **Why**: spends time, increases complexity, often achieves nothing or regresses.
- **Right**: profile with `py-spy` / `cProfile` / `memray`; capture before/after numbers; commit the benchmark script.

---

## Refactor + feature in one PR

- **Bad**: rename + restructure + add new endpoint, all in one commit.
- **Why**: review becomes impossible; rollback is all-or-nothing.
- **Right**: refactor PR (no behavior change), then feature PR.

---

> **Append new anti-patterns as you discover them. Pattern → Why → Right way.**
