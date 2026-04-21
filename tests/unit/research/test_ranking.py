"""Tests for signal ranking."""

import pandas as pd

from csm.research.ranking import CrossSectionalRanker


def test_ranker_computes_percentiles_and_quintiles() -> None:
    date: pd.Timestamp = pd.Timestamp("2024-01-31", tz="Asia/Bangkok")
    panel: pd.DataFrame = pd.DataFrame(
        {
            "mom_12_1": [5.0, 4.0, 3.0, 2.0, 1.0],
            "sharpe_mom": [5.0, 4.0, 3.0, 2.0, 1.0],
        },
        index=pd.MultiIndex.from_product([[date], ["A", "B", "C", "D", "E"]], names=["date", "symbol"]),
    )
    ranked: pd.DataFrame = CrossSectionalRanker().rank(panel, date)
    assert ranked.iloc[0]["symbol"] == "A"
    assert sorted(ranked["quintile"].tolist()) == [1, 2, 3, 4, 5]
