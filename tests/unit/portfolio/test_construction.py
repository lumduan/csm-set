"""Tests for portfolio construction."""

import pandas as pd

from csm.portfolio.construction import PortfolioConstructor


def test_top_quantile_selection_count() -> None:
    ranked: pd.DataFrame = pd.DataFrame(
        {
            "symbol": [f"S{i}" for i in range(10)],
            "quintile": [5, 5, 4, 4, 3, 3, 2, 2, 1, 1],
        }
    )
    selected: list[str] = PortfolioConstructor().select(ranked, top_quantile=0.2)
    assert len(selected) == 2
