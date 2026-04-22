"""Parquet-backed persistence for pipeline artefacts.

Keys are logical identifiers such as ``"SET:AOT"`` or ``"universe/2024-01-31"``.
The store handles all path construction; callers never touch pyarrow or file
paths directly.

Key contract:
- Keys may contain ``/`` to create subdirectory layouts (e.g. universe snapshots).
- Special characters in keys (including ``:``) are percent-encoded so the store
  is safe on all platforms.
- Keys must not be empty and must not contain path-traversal components (``..``
  or backslashes).

**Synchronous I/O — approved architectural exception:**
``ParquetStore`` performs synchronous filesystem and pyarrow I/O. This is an
explicit, documented exception to the project's async-first rule.

Rationale:

1. pyarrow's ``to_parquet`` / ``read_parquet`` are CPU-bound, memory-bound
   operations over local files — not network I/O that benefits from async.
2. The primary callers (batch scripts, ``FeaturePipeline``, ``MomentumBacktest``)
   are synchronous entry points where blocking I/O is acceptable.
3. Making the API async would require wrapping every pyarrow call in
   ``asyncio.to_thread()`` and propagating ``async``/``await`` through all
   callers — a disproportionate change for local file I/O.

If a future caller needs non-blocking parquet I/O (e.g., inside an async
coroutine), the correct pattern is:

.. code-block:: python

    await asyncio.to_thread(store.save, key, df)
    df = await asyncio.to_thread(store.load, key)
"""

import logging
from pathlib import Path
from urllib.parse import quote, unquote

import pandas as pd

from csm.data.exceptions import StoreError

logger: logging.Logger = logging.getLogger(__name__)


def _validate_key(key: str) -> None:
    """Raise ``ValueError`` if *key* is unsafe or invalid.

    Args:
        key: The logical key to validate.

    Raises:
        ValueError: If *key* is empty, whitespace-only, contains backslashes,
            or contains path-traversal components (``..`` or empty leading
            segment from a leading ``/``).
    """
    if not key.strip():
        raise ValueError(f"Store key must not be empty or whitespace: {key!r}")
    if "\\" in key:
        raise ValueError(f"Store key must not contain backslashes: {key!r}")
    for component in key.split("/"):
        if component in ("", ".."):
            raise ValueError(f"Store key contains invalid path component {component!r}: {key!r}")


def _key_to_filename(key: str) -> str:
    """Return a filesystem-safe representation of *key*.

    Uses percent-encoding (``urllib.parse.quote``) so the transformation is
    fully reversible. ``/`` is preserved as a path separator; all other
    special characters (including ``:`` and ``%``) are encoded.

    Args:
        key: Validated logical key (e.g. ``"SET:AOT"``).

    Returns:
        Filesystem-safe string (e.g. ``"SET%3AAOT"``).
    """
    return quote(key, safe="/")


def _filename_to_key(stem: str) -> str:
    """Reverse the encoding applied by :func:`_key_to_filename`.

    Args:
        stem: POSIX-style relative path stem from ``base_dir`` (no extension).

    Returns:
        Canonical logical key (e.g. ``"SET:AOT"``).
    """
    return unquote(stem)


class ParquetStore:
    """Parquet-backed key-value store for DataFrame artefacts.

    All pipeline artefacts (raw OHLCV, cleaned prices, universe snapshots,
    feature panels) are persisted here. Callers use logical string keys; the
    store handles encoding, path construction, and directory creation.

    Args:
        base_dir: Root directory for this store instance. Created automatically
            if it does not exist.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir: Path = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """Return the absolute file path for *key* (assumes key is validated)."""
        return self._base_dir / f"{_key_to_filename(key)}.parquet"

    def save(self, key: str, df: pd.DataFrame) -> None:
        """Persist *df* under *key*, overwriting any existing file.

        Args:
            key: Logical dataset identifier (e.g. ``"SET:AOT"``).
            df: DataFrame to persist. The index is stored alongside the data.

        Raises:
            ValueError: If *key* is empty, whitespace-only, contains backslashes,
                or contains path-traversal components.
            StoreError: If the underlying write fails (permissions, disk full,
                corrupt pyarrow state, etc.).
        """
        _validate_key(key)
        path: Path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            df.to_parquet(path, engine="pyarrow", index=True)
            logger.info("Saved dataset", extra={"key": key, "path": str(path)})
        except Exception as exc:  # noqa: BLE001
            raise StoreError(f"Failed to save dataset {key!r}: {exc}") from exc

    def load(self, key: str) -> pd.DataFrame:
        """Load and return the DataFrame stored under *key*.

        Args:
            key: Logical dataset identifier.

        Returns:
            The persisted DataFrame, including its original index.

        Raises:
            ValueError: If *key* is invalid (see :meth:`save`).
            KeyError: If no dataset file exists for *key*.
            StoreError: If the file exists but cannot be read.
        """
        _validate_key(key)
        path: Path = self._resolve(key)
        if not path.is_file():
            raise KeyError(key)
        try:
            return pd.read_parquet(path, engine="pyarrow")
        except Exception as exc:  # noqa: BLE001
            raise StoreError(f"Failed to load dataset {key!r}: {exc}") from exc

    def exists(self, key: str) -> bool:
        """Return ``True`` if a dataset file exists for *key*.

        Args:
            key: Logical dataset identifier.

        Returns:
            ``True`` if the parquet file is present and is a regular file;
            ``False`` otherwise.

        Raises:
            ValueError: If *key* is invalid (see :meth:`save`).
        """
        _validate_key(key)
        return self._resolve(key).is_file()

    def list_keys(self) -> list[str]:
        """Return a sorted list of all stored logical keys.

        Keys are reconstructed from filenames by reversing the percent-encoding
        applied during :meth:`save`. ``/`` is used as the path separator
        regardless of the host OS.

        Returns:
            Sorted list of canonical key strings (e.g. ``["SET:ADVANC", "SET:AOT"]``).
        """
        keys: list[str] = []
        for path in self._base_dir.rglob("*.parquet"):
            if path.is_file():
                posix_stem: str = path.relative_to(self._base_dir).with_suffix("").as_posix()
                keys.append(_filename_to_key(posix_stem))
        return sorted(keys)

    def delete(self, key: str) -> None:
        """Remove the file stored under *key*.

        Args:
            key: Logical dataset identifier.

        Raises:
            ValueError: If *key* is invalid (see :meth:`save`).
            KeyError: If no dataset file exists for *key*.
            StoreError: If the file exists but cannot be deleted.
        """
        _validate_key(key)
        path: Path = self._resolve(key)
        if not path.is_file():
            raise KeyError(key)
        try:
            path.unlink()
            logger.info("Deleted dataset", extra={"key": key, "path": str(path)})
        except Exception as exc:  # noqa: BLE001
            raise StoreError(f"Failed to delete dataset {key!r}: {exc}") from exc


__all__: list[str] = ["ParquetStore"]
