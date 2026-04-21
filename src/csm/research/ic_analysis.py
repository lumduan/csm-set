"""Information coefficient analysis utilities."""

import logging

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class ICAnalyzer:
    """Compute information coefficient diagnostics for signals."""

    def compute_ic(self, signals: pd.DataFrame, forward_returns: pd.DataFrame) -> pd.DataFrame:
        """Compute Pearson IC per date across the common symbol cross-section."""

        common_dates: pd.Index = signals.index.intersection(forward_returns.index)
        common_columns: pd.Index = signals.columns.intersection(forward_returns.columns)
        ic_rows: list[dict[str, float | pd.Timestamp]] = []
        for date in common_dates:
            signal_row: pd.Series = signals.loc[date, common_columns].astype(float)
            return_row: pd.Series = forward_returns.loc[date, common_columns].astype(float)
            ic_rows.append({"date": pd.Timestamp(date), "ic": float(signal_row.corr(return_row, method="pearson"))})
        return pd.DataFrame(ic_rows).set_index("date") if ic_rows else pd.DataFrame(columns=["ic"])

    def compute_rank_ic(self, signals: pd.DataFrame, forward_returns: pd.DataFrame) -> pd.DataFrame:
        """Compute Spearman rank IC per date across the common symbol cross-section."""

        common_dates: pd.Index = signals.index.intersection(forward_returns.index)
        common_columns: pd.Index = signals.columns.intersection(forward_returns.columns)
        ic_rows: list[dict[str, float | pd.Timestamp]] = []
        for date in common_dates:
            signal_row: pd.Series = signals.loc[date, common_columns].astype(float)
            return_row: pd.Series = forward_returns.loc[date, common_columns].astype(float)
            ic_rows.append(
                {
                    "date": pd.Timestamp(date),
                    "rank_ic": float(signal_row.corr(return_row, method="spearman")),
                }
            )
        return pd.DataFrame(ic_rows).set_index("date") if ic_rows else pd.DataFrame(columns=["rank_ic"])

    def icir(self, ic_series: pd.Series) -> float:
        """Compute the information coefficient information ratio."""

        std: float = float(ic_series.std(ddof=0))
        return 0.0 if std == 0.0 else float(ic_series.mean() / std)

    def decay_curve(
        self,
        prices: pd.DataFrame,
        signal_date: pd.Timestamp,
        signal: pd.Series,
        horizons: list[int],
    ) -> pd.DataFrame:
        """Compute IC decay across multiple forward horizons."""

        monthly_prices: pd.DataFrame = prices.resample("ME").last().sort_index()
        if signal_date not in monthly_prices.index:
            signal_date = monthly_prices.index[monthly_prices.index.get_indexer([signal_date], method="ffill")[0]]
        start_position: int = int(monthly_prices.index.get_loc(signal_date))
        rows: list[dict[str, float | int]] = []
        for horizon in horizons:
            if start_position + horizon >= len(monthly_prices.index):
                continue
            forward_return: pd.Series = (
                monthly_prices.iloc[start_position + horizon] / monthly_prices.iloc[start_position]
            ) - 1.0
            aligned_signal: pd.Series = signal.reindex(forward_return.index).dropna()
            aligned_returns: pd.Series = forward_return.reindex(aligned_signal.index).dropna()
            aligned_signal = aligned_signal.reindex(aligned_returns.index)
            rows.append(
                {
                    "horizon_months": horizon,
                    "ic": float(aligned_signal.corr(aligned_returns, method="pearson")),
                    "rank_ic": float(aligned_signal.corr(aligned_returns, method="spearman")),
                }
            )
        return pd.DataFrame(rows)


__all__: list[str] = ["ICAnalyzer"]