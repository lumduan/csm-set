# Coding Standards — csm-set

Concrete, enforceable rules. If you can't comply, document why in code with a `# noqa` + reason.

## Naming

- **Modules / functions / variables**: `snake_case`.
- **Classes / Pydantic models / TypedDicts**: `PascalCase`.
- **Constants / sentinels**: `SCREAMING_SNAKE_CASE`.
- **Private**: `_leading_underscore` (module-private) or class-private as needed.
- **Avoid abbreviations** except established domain terms: NAV, ROC, RSI, P&L, OHLCV, SET.

## Typing

- Full type annotations on every function — args and return.
- No bare `Any`. If unavoidable, justify in a comment.
- Prefer `Sequence`, `Mapping`, `Iterable` for parameters; `list`, `dict` for returns when concrete.
- Use `Optional[X]` only when `None` is meaningful; otherwise omit the default.
- `from __future__ import annotations` at top of every `src/csm/` module (Py 3.11 forward-compat).
- Pydantic models for all data crossing module / process boundaries.

## File Size & Complexity

- Target ≤ 400 lines per `.py` file.
- Functions ≤ ~50 lines unless cohesion demands more.
- Cyclomatic complexity flagged by ruff `C901`: refactor on hit.

## Errors

- Define module-local exceptions in each subpackage's `errors.py`.
- Inherit from a single `CsmError(Exception)` root.
- Never `raise Exception(...)`; never `except Exception: pass`.
- Catch the narrowest type that captures the failure mode.

## Imports

- ruff-isort sorted: stdlib → third-party → local, blank line between groups.
- No relative imports beyond one level (`from . import x`, never `from ...util import y`).
- No wildcard imports (`from x import *`).

## Logging

- `logger = logging.getLogger(__name__)` at module top.
- **Never** `print` in `src/csm/`. (`scripts/` and `examples/` may, sparingly.)
- Use structured kwargs where the logger supports it; otherwise use `%` formatting (`logger.info("fetched %d rows", n)`) — not f-strings, so log level filtering still saves work.
- Never log secrets, bearer tokens, or full request bodies.

## Async

- Every public function performing I/O is `async def`.
- Use `httpx.AsyncClient` (not `requests`).
- Use `asyncio.gather` for independent awaitables.
- Always set `timeout=` on `httpx` calls.
- Use `async with` for resource management.

## pandas / numpy

- Vectorize. No row-wise `apply`, no `iterrows` on hot paths.
- Tz-aware `Timestamp` only at boundaries — never mix tz-naive and tz-aware in a single frame.
- Empty-frame guard at the top of every public signal/portfolio function.
- Column dtypes set explicitly when reading Parquet (`columns=[...]`, dtype assertions in tests).

## Docstrings

Google style, mandatory on public functions:

```python
async def compute_momentum(
    prices: pd.DataFrame,
    lookback: int = 252,
) -> pd.Series:
    """Rank-based cross-sectional momentum.

    Args:
        prices: Wide-format price frame, index tz-aware (Asia/Bangkok), columns are SET symbols.
        lookback: Window length in trading days. Defaults to 252.

    Returns:
        Series indexed by symbol with cross-sectional rank (0..1).

    Raises:
        ValueError: If `prices` is empty or has a tz-naive index.

    Example:
        >>> ranks = await compute_momentum(prices, lookback=126)
    """
```

## Tests

- One test file per source file, mirroring path.
- `@pytest.mark.asyncio` for async tests.
- No network in unit tests; integration tests behind markers.
- See [agent](../agents/test-engineer.md).
