"""Signal ranking utilities for cross-sectional momentum."""

import logging

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class CrossSectionalRanker:
    """Rank symbols cross-sectionally from a feature panel."""

    def rank(self, feature_matrix: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
        """Rank symbols for a specific rebalance date.

        Args:
            feature_matrix: MultiIndex feature panel indexed by `(date, symbol)`.
            date: Rebalance date to rank.

        Returns:
            DataFrame with symbol, rank, z_score, and quintile columns.
        """

        snapshot: pd.DataFrame = feature_matrix.xs(date, level="date")
        numeric_columns: list[str] = snapshot.select_dtypes(include="number").columns.tolist()
        composite: pd.Series = snapshot[numeric_columns].mean(axis=1)
        std: float = float(composite.std(ddof=0))
        mean: float = float(composite.mean())
        z_score: pd.Series = pd.Series(0.0, index=composite.index, name="z_score")
        if std != 0.0:
            z_score = (composite - mean) / std
            z_score.name = "z_score"
        rank_pct: pd.Series = z_score.rank(pct=True, method="first")
        quintile: pd.Series = pd.qcut(rank_pct.rank(method="first"), q=5, labels=[1, 2, 3, 4, 5]).astype(int)
        result: pd.DataFrame = pd.DataFrame(
            {
                "symbol": z_score.index,
                "rank": rank_pct.to_numpy(),
                "z_score": z_score.to_numpy(),
                "quintile": quintile.to_numpy(),
            }
        ).sort_values("rank", ascending=False, ignore_index=True)
        logger.info("Ranked cross section", extra={"date": str(date), "count": len(result.index)})
        return result


__all__: list[str] = ["CrossSectionalRanker"]