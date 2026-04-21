"""Sector-relative feature computations."""

import logging

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class SectorFeatures:
    """Compute sector-relative return features."""

    def relative_strength(self, prices: pd.DataFrame, sector_map: dict[str, str]) -> pd.DataFrame:
        """Compute symbol return minus sector median return over three months.

        Args:
            prices: Wide price matrix with symbols as columns.
            sector_map: Mapping from symbol to sector code.

        Returns:
            DataFrame indexed by symbol with sector, sector_return, and relative_strength.
        """

        trailing_prices: pd.DataFrame = prices.tail(63)
        returns: pd.Series = (trailing_prices.iloc[-1] / trailing_prices.iloc[0]) - 1.0
        rows: list[dict[str, str | float]] = []
        for symbol, value in returns.items():
            sector: str = sector_map.get(symbol, "UNKNOWN")
            sector_symbols: list[str] = [
                name for name, code in sector_map.items() if code == sector
            ]
            sector_return: float = (
                float(returns.reindex(sector_symbols).median()) if sector_symbols else 0.0
            )
            rows.append(
                {
                    "symbol": symbol,
                    "sector": sector,
                    "sector_return": sector_return,
                    "relative_strength": float(value - sector_return),
                }
            )
        result: pd.DataFrame = pd.DataFrame(rows).set_index("symbol").sort_index()
        logger.info("Computed sector relative strength", extra={"symbols": len(result.index)})
        return result


__all__: list[str] = ["SectorFeatures"]
