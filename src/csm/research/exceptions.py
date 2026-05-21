"""Custom exceptions for the research layer."""


class ResearchError(Exception):
    """Base exception for all research layer errors."""


class BacktestError(ResearchError):
    """Raised when the backtest engine encounters an unrecoverable error."""


class ReportError(ResearchError):
    """Raised when strategy-report construction receives invalid inputs."""


__all__: list[str] = ["BacktestError", "ReportError", "ResearchError"]
