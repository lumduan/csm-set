"""Module-local exceptions for the execution subpackage."""

from __future__ import annotations


class ExecutionError(Exception):
    """Base class for all execution-layer failures."""


class TradePairingError(ExecutionError):
    """Raised when a sequence of rebalance fills cannot be paired into round-trip trades."""


__all__: list[str] = ["ExecutionError", "TradePairingError"]
