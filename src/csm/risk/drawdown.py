"""Drawdown analysis helpers."""

import logging

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class DrawdownAnalyzer:
    """Compute drawdown series and recovery episodes."""

    def max_drawdown(self, equity_curve: pd.Series) -> float:
        """Return the maximum drawdown as a negative float."""

        underwater: pd.Series = self.underwater_curve(equity_curve)
        return float(underwater.min())

    def underwater_curve(self, equity_curve: pd.Series) -> pd.Series:
        """Return the drawdown from the running peak."""

        return equity_curve / equity_curve.cummax() - 1.0

    def recovery_periods(self, equity_curve: pd.Series) -> pd.DataFrame:
        """Identify drawdown and recovery episodes."""

        underwater: pd.Series = self.underwater_curve(equity_curve)
        rows: list[dict[str, object]] = []
        in_drawdown: bool = False
        start: pd.Timestamp | None = None
        trough: pd.Timestamp | None = None
        trough_depth: float = 0.0
        for date, value in underwater.items():
            if value < 0.0 and not in_drawdown:
                in_drawdown = True
                start = pd.Timestamp(date)
                trough = pd.Timestamp(date)
                trough_depth = float(value)
            elif value < trough_depth and in_drawdown:
                trough = pd.Timestamp(date)
                trough_depth = float(value)
            elif value >= 0.0 and in_drawdown and start is not None and trough is not None:
                recovery: pd.Timestamp = pd.Timestamp(date)
                duration_days = int((recovery - start).days)
                rows.append(
                    {
                        "start": start,
                        "trough": trough,
                        "recovery": recovery,
                        "depth": trough_depth,
                        "duration_days": duration_days,
                        "recovery_months": round(duration_days / 30.5, 1),
                    }
                )
                in_drawdown = False
        return pd.DataFrame(rows)


__all__: list[str] = ["DrawdownAnalyzer"]
