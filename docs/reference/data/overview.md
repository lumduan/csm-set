# Data Layer — Module Reference

The `csm.data` subpackage handles OHLCV data ingestion (tvkit + parquet), cleaning, universe construction, and symbol filtering. All I/O is async at the loader boundary; downstream modules operate on in-memory DataFrames.

## Module index

| Module | Purpose |
|--------|---------|
| `src/csm/data/loader.py` | Fetch OHLCV data via tvkit; `OHLCVLoader`, `Adjustment` enum |
| `src/csm/data/store.py` | Parquet-based persistence layer; `ParquetStore` |
| `src/csm/data/universe.py` | Monthly universe snapshots with liquidity/listing filters; `UniverseBuilder` |
| `src/csm/data/cleaner.py` | Price cleaning (forward-fill, coverage, winsorisation); `PriceCleaner` |
| `src/csm/data/symbol_filter.py` | Symbol-level filtering by security type; `filter_symbols`, `SecurityType` |
| `src/csm/data/exceptions.py` | Data-layer exceptions: `DataError`, `FetchError`, `StoreError`, `UniverseError`, `DataAccessError` |

## Public callables

### `class OHLCVLoader`

- **Defined in:** `src/csm/data/loader.py`
- **Purpose:** Fetches OHLCV data from TradingView via tvkit. Accepts a `Settings` instance for configuration.
- **Constructor:** `__init__(self, settings: Settings) -> None`
- **Key methods:**
  - `async fetch(self, symbol: str, interval: str = "1D", bars: int = 800, adjustment: Adjustment = Adjustment.DIVIDENDS) -> pd.DataFrame` — fetches OHLCV for a single symbol.
  - `async fetch_batch(self, symbols: list[str], interval: str = "1D", bars: int = 800, adjustment: Adjustment = Adjustment.DIVIDENDS) -> dict[str, pd.DataFrame]` — fetches OHLCV for multiple symbols concurrently with semaphore-limited concurrency.
- **Behaviour:**
  - Returns a DataFrame with columns `open, high, low, close, volume, adj_close`, indexed by `pd.Timestamp` in UTC.
  - Retries transient network failures per `Settings.tvkit_retry_attempts`.
  - `Adjustment.DIVIDENDS` applies total-return backward adjustment (recommended for backtesting).
  - `Adjustment.SPLITS` applies split-only adjustment (legacy pre-tvkit 0.11.0 behaviour).
- **Example:**
  ```python
  from csm.config.settings import settings
  from csm.data.loader import OHLCVLoader

  loader = OHLCVLoader(settings)
  df = await loader.fetch("PTT", interval="1D", bars=500)
  ```
- **Tested in:** `tests/unit/data/test_loader.py`

### `class ParquetStore`

- **Defined in:** `src/csm/data/store.py`
- **Purpose:** Key-value store backed by Parquet files on disk. Keys are validated and mapped to filenames under a base directory.
- **Constructor:** `__init__(self, base_dir: Path) -> None`
- **Key methods:**
  - `save(self, key: str, df: pd.DataFrame) -> None` — writes a DataFrame to `{base_dir}/{key}.parquet` with snappy compression.
  - `load(self, key: str) -> pd.DataFrame` — reads a DataFrame from `{base_dir}/{key}.parquet`. Raises `StoreError` if the key is not found.
  - `exists(self, key: str) -> bool` — returns True if the key exists on disk.
  - `list_keys(self) -> list[str]` — returns all stored keys.
  - `delete(self, key: str) -> None` — removes the key from disk.
- **Behaviour:** Keys are validated (alphanumeric + underscores/hyphens only). Filenames are derived from keys with a `.parquet` suffix.
- **Example:**
  ```python
  from pathlib import Path
  from csm.data.store import ParquetStore

  store = ParquetStore(Path("./data/processed"))
  store.save("PTT_1D", df)
  df = store.load("PTT_1D")
  ```

### `class UniverseBuilder`

- **Defined in:** `src/csm/data/universe.py`
- **Purpose:** Constructs monthly universe snapshots for the strategy. Applies listing age, liquidity, and security-type filters.
- **Constructor:** `__init__(self, store: ParquetStore, settings: Settings) -> None`
- **Key methods:**
  - `filter(self, symbol: str, asof: pd.Timestamp) -> bool` — returns True if the symbol passes all universe criteria at the given date.
  - `build_snapshot(self, asof: pd.Timestamp, symbols: list[str]) -> list[str]` — returns the list of symbols that pass filters at the given date.
  - `build_all_snapshots(self, start: pd.Timestamp, end: pd.Timestamp, symbols: list[str], freq: str = "ME") -> dict[pd.Timestamp, list[str]]` — returns a dict mapping each month-end to the qualifying symbols.
- **Behaviour:**
  - Requires >= 12 months of price history before a stock enters the universe (listing age gate).
  - Applies ADV threshold (>= 100M THB 20-day average daily value).
  - Excludes non-common-stock security types (warrants, preferred shares, ETFs) via `filter_symbols`.
- **Example:**
  ```python
  builder = UniverseBuilder(store, settings)
  symbols = builder.build_snapshot(pd.Timestamp("2025-01-31", tz="Asia/Bangkok"), all_symbols)
  ```

### `class PriceCleaner`

- **Defined in:** `src/csm/data/cleaner.py`
- **Purpose:** Applies cleaning transformations to raw OHLCV DataFrames.
- **Key methods:**
  - `forward_fill_gaps(self, df: pd.DataFrame) -> pd.DataFrame` — forward-fills missing trading days (non-trading days, holidays).
  - `drop_low_coverage(self, df: pd.DataFrame, threshold: float = 0.66) -> pd.DataFrame | None` — drops symbols with fewer than `threshold` fraction of non-null observations. Returns None if the symbol should be excluded entirely.
  - `winsorise_returns(self, df: pd.DataFrame, sigma: float = 5.0) -> pd.DataFrame` — clips daily returns to ±`sigma` standard deviations.
  - `clean(self, df: pd.DataFrame) -> pd.DataFrame | None` — runs the full cleaning pipeline (gap fill → coverage check → winsorise). Returns None if the symbol fails coverage.
- **Example:**
  ```python
  cleaner = PriceCleaner()
  cleaned = cleaner.clean(raw_df)
  if cleaned is not None:
      store.save(f"{symbol}_1D", cleaned)
  ```

### `filter_symbols(symbols: list[dict], security_types: frozenset[SecurityType]) -> list[dict]`

- **Defined in:** `src/csm/data/symbol_filter.py`
- **Purpose:** Filters a list of symbol metadata dicts to only those matching the given security types.
- **Behaviour:** Uses `settfex` to identify security types. Filters out warrants, preferred shares, ETFs, and other non-common-stock instruments.
- **Example:**
  ```python
  from csm.data.symbol_filter import filter_symbols, SecurityType
  common = filter_symbols(symbol_metadata, frozenset({SecurityType.COMMON}))
  ```

### `class SecurityType(StrEnum)`

- **Defined in:** `src/csm/data/symbol_filter.py`
- **Purpose:** Enum of SET security types: `COMMON`, `PREFERRED`, `WARRANT`, `ETF`, `DR`, `UNKNOWN`.

## Cross-references

- Used by: `src/csm/features/pipeline.py` (builds panel from cleaned price data), `scripts/fetch_history.py` (batch-loads OHLCV)
- Tested in: `tests/unit/data/test_loader.py`, `tests/unit/data/test_store.py`, `tests/unit/data/test_cleaner.py`, `tests/unit/data/test_symbol_filter.py`
- Concept: [Architecture Overview](../../architecture/overview.md) § Runtime data flow
