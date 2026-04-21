"""Custom exceptions for the features layer."""


class FeatureError(Exception):
    """Base exception for all feature computation errors."""


class InsufficientDataError(FeatureError):
    """Raised when a symbol does not have enough history for the requested lookback."""


__all__: list[str] = ["FeatureError", "InsufficientDataError"]
