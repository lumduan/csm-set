"""Custom exceptions for portfolio construction."""


class PortfolioError(Exception):
    """Base exception for portfolio construction errors."""


class OptimizationError(PortfolioError):
    """Raised when weight optimization fails to converge."""


class SelectionError(PortfolioError):
    """Raised when portfolio selection fails (e.g., empty cross-section after filtering)."""


class CircuitBreakerTripped(PortfolioError):
    """Raised when drawdown circuit breaker trips in live mode.

    In backtest mode the breaker applies safe-mode equity but never raises.
    This exception is reserved for Phase 5 live-trading wiring.
    """


__all__: list[str] = [
    "CircuitBreakerTripped",
    "OptimizationError",
    "PortfolioError",
    "SelectionError",
]
