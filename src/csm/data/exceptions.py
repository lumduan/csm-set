"""Custom exceptions for the data layer."""


class DataError(Exception):
    """Base exception for all data layer errors."""


class DataAccessError(DataError):
    """Raised when data access is attempted in public mode."""


class FetchError(DataError):
    """Raised when a tvkit fetch fails after all retries."""


class UniverseError(DataError):
    """Raised when universe construction fails or produces an empty result."""


class StoreError(DataError):
    """Raised when reading from or writing to the parquet store fails."""


__all__: list[str] = [
    "DataAccessError",
    "DataError",
    "FetchError",
    "StoreError",
    "UniverseError",
]
