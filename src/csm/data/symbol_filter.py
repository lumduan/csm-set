"""SET symbol type classification and filtering utilities.

Each symbol listed on the Stock Exchange of Thailand carries a ``security_type``
code that determines the instrument class.  This module provides a typed enum
for those codes and a filter function so that pipelines can select the desired
instrument classes before fetching OHLCV data.

Typical usage — stocks only (the default for the CSM pipeline)::

    symbols = filter_symbols(all_set_stocks, include={SecurityType.STOCK})

All security types available on SET::

    SecurityType.STOCK       "S"  — Common stock (e.g. SET:AOT, SET:CPALL)
    SecurityType.FUTURES     "F"  — Futures contracts (e.g. SET:PTT-F)
    SecurityType.DW          "V"  — Derivative Warrants on Thai stocks (e.g. SET:PTT01C2606T)
    SecurityType.WARRANT     "W"  — Company-issued warrants (e.g. SET:A5-W4)
    SecurityType.FOREIGN_DW  "X"  — Derivative Warrants on foreign stocks (e.g. SET:AAPL01)
    SecurityType.PREFERRED   "P"  — Preferred shares (e.g. SET:BH-P)
    SecurityType.CONVERTIBLE "Q"  — Convertible preferred shares (e.g. SET:BH-Q)
    SecurityType.ETF         "L"  — ETF / Infrastructure funds (e.g. SET:1DIV)
    SecurityType.UNIT_TRUST  "U"  — Unit trusts (e.g. SET:SCBSET)
"""

from enum import StrEnum
from typing import Protocol


class SecurityType(StrEnum):
    """SET instrument type codes as returned by settfex ``security_type`` field."""

    STOCK = "S"
    """Common stock — the primary equity instrument for CSM momentum research."""

    FUTURES = "F"
    """Futures contracts on underlying SET stocks or indices."""

    DW = "V"
    """Derivative Warrants (Call/Put) on Thai-listed underlying stocks."""

    WARRANT = "W"
    """Company-issued warrants (rights to buy new shares)."""

    FOREIGN_DW = "X"
    """Derivative Warrants on foreign underlying stocks (e.g. AAPL, MSFT)."""

    PREFERRED = "P"
    """Preferred shares."""

    CONVERTIBLE = "Q"
    """Convertible preferred shares."""

    ETF = "L"
    """Exchange-traded funds and Infrastructure Investment Trusts (IFF)."""

    UNIT_TRUST = "U"
    """Unit trusts and REIT-like listed funds."""


# Human-readable label for each type — used in logging and CLI help text
SECURITY_TYPE_LABELS: dict[SecurityType, str] = {
    SecurityType.STOCK: "Common stock",
    SecurityType.FUTURES: "Futures",
    SecurityType.DW: "Derivative Warrant (Thai underlying)",
    SecurityType.WARRANT: "Company warrant",
    SecurityType.FOREIGN_DW: "Derivative Warrant (foreign underlying)",
    SecurityType.PREFERRED: "Preferred share",
    SecurityType.CONVERTIBLE: "Convertible preferred share",
    SecurityType.ETF: "ETF / Infrastructure fund",
    SecurityType.UNIT_TRUST: "Unit trust",
}

# Default set: common stocks only — used by build_universe.py
DEFAULT_SECURITY_TYPES: frozenset[SecurityType] = frozenset({SecurityType.STOCK})


class _HasSecurityType(Protocol):
    """Protocol satisfied by settfex ``StockInfo`` objects."""

    symbol: str
    security_type: str


def filter_symbols(
    stocks: list[_HasSecurityType],
    include: frozenset[SecurityType] | set[SecurityType] = DEFAULT_SECURITY_TYPES,
) -> list[_HasSecurityType]:
    """Return only the entries whose ``security_type`` is in *include*.

    Args:
        stocks: List of settfex ``StockInfo`` objects (or any objects with
            ``symbol: str`` and ``security_type: str`` attributes).
        include: Security types to keep.  Defaults to ``{SecurityType.STOCK}``
            which selects common stocks only.

    Returns:
        Filtered list preserving the original order.

    Example::

        from csm.data.symbol_filter import SecurityType, filter_symbols
        stocks_only = filter_symbols(all_set, include={SecurityType.STOCK})
        stocks_and_etfs = filter_symbols(all_set, include={SecurityType.STOCK, SecurityType.ETF})
    """
    valid_codes = {t.value for t in include}
    return [s for s in stocks if s.security_type in valid_codes]


def parse_security_types(codes: list[str]) -> frozenset[SecurityType]:
    """Parse a list of security type code strings into a ``frozenset[SecurityType]``.

    Accepts uppercase or lowercase codes (e.g. ``"S"``, ``"s"``).

    Args:
        codes: List of single-letter security type codes.

    Returns:
        Frozenset of matching ``SecurityType`` members.

    Raises:
        ValueError: If any code does not match a known ``SecurityType``.
    """
    result: set[SecurityType] = set()
    valid = {t.value: t for t in SecurityType}
    for code in codes:
        upper = code.upper()
        if upper not in valid:
            known = ", ".join(sorted(valid.keys()))
            raise ValueError(f"Unknown security type code {code!r}. Known codes: {known}")
        result.add(valid[upper])
    return frozenset(result)


__all__: list[str] = [
    "SecurityType",
    "SECURITY_TYPE_LABELS",
    "DEFAULT_SECURITY_TYPES",
    "filter_symbols",
    "parse_security_types",
]
