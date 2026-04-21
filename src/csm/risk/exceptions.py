"""Custom exceptions for the risk layer."""


class RiskError(Exception):
    """Base exception for risk layer errors."""


__all__: list[str] = ["RiskError"]