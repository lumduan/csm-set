"""Custom exceptions for portfolio construction."""


class PortfolioError(Exception):
    """Base exception for portfolio construction errors."""


class OptimizationError(PortfolioError):
    """Raised when weight optimization fails to converge."""


__all__: list[str] = ["OptimizationError", "PortfolioError"]