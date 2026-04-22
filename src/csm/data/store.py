"""Parquet-backed persistence for intermediate research artifacts."""

import logging
from pathlib import Path

import pandas as pd

from csm.data.exceptions import StoreError

logger: logging.Logger = logging.getLogger(__name__)


class ParquetStore:
    """Simple parquet store keyed by logical dataset name."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir: Path = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, df: pd.DataFrame) -> Path:
        """Persist a DataFrame to parquet.

        Args:
            name: Logical dataset name.
            df: DataFrame to persist.

        Returns:
            Path written to disk.

        Raises:
            StoreError: If writing fails.
        """

        path: Path = self._base_dir / f"{name}.parquet"
        try:
            df.to_parquet(path, engine="pyarrow")
            logger.info("Saved dataset", extra={"name": name, "path": str(path)})
            return path
        except Exception as exc:  # noqa: BLE001
            raise StoreError(f"Failed to save dataset {name}: {exc}") from exc

    def load(self, name: str) -> pd.DataFrame:
        """Load a DataFrame from parquet.

        Args:
            name: Logical dataset name.

        Returns:
            Loaded DataFrame.

        Raises:
            StoreError: If the file is missing or unreadable.
        """

        path: Path = self._base_dir / f"{name}.parquet"
        if not path.exists():
            raise StoreError(f"Dataset does not exist: {name}")
        try:
            return pd.read_parquet(path, engine="pyarrow")
        except Exception as exc:  # noqa: BLE001
            raise StoreError(f"Failed to load dataset {name}: {exc}") from exc

    def exists(self, name: str) -> bool:
        """Check whether a dataset exists in the store."""

        return (self._base_dir / f"{name}.parquet").exists()

    def list_keys(self) -> list[str]:
        """List stored dataset keys in sorted order."""

        keys: list[str] = sorted(path.stem for path in self._base_dir.glob("*.parquet"))
        return keys


__all__: list[str] = ["ParquetStore"]