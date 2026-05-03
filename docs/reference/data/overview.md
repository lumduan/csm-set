# Data Module Reference

Reference for `src/csm/data/` — the data ingestion, storage, cleaning, and universe construction layer. This subpackage handles all raw-data operations: fetching OHLCV from TradingView via tvkit, persisting DataFrames as Parquet files, filtering symbols by security type, building investable-universe snapshots, and cleaning prices for downstream signal computation.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/data/loader.py` | Async OHLCV fetcher backed by tvkit; public-mode guard; retry with backoff |
| `src/csm/data/store.py` | Parquet-backed key-value store for DataFrame artefacts; synchronous I/O (explicit architectural exception) |
| `src/csm/data/universe.py` | Universe builder — applies price/volume/coverage filters; persists dated snapshots |
| `src/csm/data/cleaner.py` | Per-symbol OHLCV cleaner — forward-fill gaps, drop low-coverage symbols, winsorise returns |
| `src/csm/data/symbol_filter.py` | TradingView symbol type filtering (stock vs. index vs. futures etc.) |
| `src/csm/data/exceptions.py` | Data-layer exception classes (`DataAccessError`, `FetchError`, `StoreError`) |

## Public callables

### `OHLCVLoader(settings: Settings)`

- **Defined in:** `src/csm/data/loader.py`
- **Purpose:** Async OHLCV fetcher using tvkit. Wraps a `asyncio.Semaphore` for concurrency control.
- **Behaviour:**
  - `fetch(symbol, interval, bars, adjustment)` — fetches a single symbol; retries on transient errors; returns `pd.DataFrame` with columns `["open", "high", "low", "close", "volume"]` and `DatetimeIndex` (tz=`Asia/Bangkok`)
  - `fetch_batch(symbols, interval, bars, adjustment)` — fetches multiple symbols concurrently, bounded by `settings.tvkit_concurrency`; per-symbol failures are logged and the symbol is omitted from the result
  - Raises `DataAccessError` immediately if `settings.public_mode` is True (no network call)
  - Raises `FetchError` if all retry attempts fail or a non-transient error occurs
- **Example:**
  ```python
  from csm.config.settings import settings
  from csm.data.loader import OHLCVLoader

  loader = OHLCVLoader(settings)
  df = await loader.fetch("SET:AOT", interval="1D", bars=500)
  results = await loader.fetch_batch(["SET:AOT", "SET:ADVANC"], "1D", 500)
  ```

### `ParquetStore(base_dir: Path)`

- **Defined in:** `src/csm/data/store.py`
- **Purpose:** Parquet-backed key-value persistence for DataFrames. Callers use logical string keys (e.g., `"SET:AOT"`, `"universe/2024-01-31"`); the store handles percent-encoding of special characters and path construction.
- **Behaviour:**
  - `save(key, df)` — persist a DataFrame under a logical key; overwrites existing files; creates parent directories automatically
  - `load(key)` — load and return a DataFrame; raises `KeyError` if not found
  - `exists(key)` — return `True` if the dataset file exists
  - `list_keys()` — return sorted list of all stored keys
  - `delete(key)` — remove the stored file; raises `KeyError` if not found
  - Synchronous I/O — this is a documented architectural exception to the project's async-first rule (pyarrow I/O is CPU-bound local file I/O, not network I/O)
- **Example:**
  ```python
  from pathlib import Path
  from csm.data.store import ParquetStore

  store = ParquetStore(Path("./data/processed"))
  store.save("SET:AOT", df)
  loaded = store.load("SET:AOT")
  all_keys = store.list_keys()  # ["SET:ADVANC", "SET:AOT", "universe/2024-01-31", ...]
  ```

### `UniverseBuilder(store: ParquetStore, settings: Settings)`

- **Defined in:** `src/csm/data/universe.py`
- **Purpose:** Builds dated universe snapshots by applying sequential filters (price, volume, coverage) to OHLCV data. Produces one snapshot per rebalance date saved under key `universe/{YYYY-MM-DD}`.
- **Behaviour:**
  - `filter(symbol, asof)` — returns `True` if the symbol passes price ≥ 1 THB, trailing 90-day avg volume ≥ 100M THB, and data coverage ≥ 80% filters as of the given date (no look-ahead)
  - `build_snapshot(asof, symbols)` — returns sorted list of passing symbols for one date
  - `build_all_snapshots(symbols, rebalance_dates, snapshot_store)` — builds and persists one snapshot per rebalance date
- **Example:**
  ```python
  builder = UniverseBuilder(store, settings)
  passing = builder.build_snapshot(pd.Timestamp("2024-01-31"), ["SET:AOT", "SET:ADVANC"])
  builder.build_all_snapshots(symbols, rebalance_dates)
  ```

### `PriceCleaner`

- **Defined in:** `src/csm/data/cleaner.py`
- **Purpose:** Stateless per-symbol OHLCV cleaner. All methods are pure transforms.
- **Behaviour:**
  - `forward_fill_gaps(df, max_gap_days=5)` — forward-fills NaN values for gaps of ≤ `max_gap_days` consecutive rows
  - `drop_low_coverage(df, min_coverage=0.80, window_years=1)` — returns `None` if any rolling window has insufficient close coverage; returns the DataFrame unchanged otherwise
  - `winsorise_returns(df, lower=0.01, upper=0.99)` — clips extreme daily close returns at the given percentile bounds and back-computes the close series
  - `clean(df)` — applies the full pipeline: `forward_fill_gaps` → `drop_low_coverage` → `winsorise_returns`; returns `None` if the symbol is dropped
- **Example:**
  ```python
  from csm.data.cleaner import PriceCleaner

  cleaner = PriceCleaner()
  cleaned = cleaner.clean(raw_df)  # pd.DataFrame or None if dropped
  ```

### `filter_symbols(codes: list[str], ...) -> list[str]`

- **Defined in:** `src/csm/data/symbol_filter.py`
- **Purpose:** Filter a list of TradingView symbol codes by security type.
- **Example:**
  ```python
  from csm.data.symbol_filter import filter_symbols, SecurityType

  stocks = filter_symbols(all_tv_symbols, keep_types={SecurityType.STOCK})
  ```

## Cross-references

- Used by: `api/routers/universe.py`, `scripts/fetch_history.py`, `scripts/build_universe.py`, `src/csm/features/pipeline.py`
- Tested in: `tests/unit/data/`, `tests/integration/`
- Concept: `docs/architecture/overview.md` § Runtime data flow
