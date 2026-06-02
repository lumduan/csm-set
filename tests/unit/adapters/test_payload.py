"""Unit tests for :mod:`csm.adapters.payload`."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pandas as pd

from csm.adapters.payload import (
    DEFAULT_STRATEGY_TYPE,
    _series_to_equity_curve,
    build_ingestion_payload,
)
from csm.live.portfolio import LivePortfolioMetrics


def _metrics(
    *,
    total_value: float = 1_000_000.0,
    cash_balance: float = 50_000.0,
    daily_return: float = 0.0125,
    cumulative_return: float = 0.123,
    max_drawdown: float = -0.046,
    sharpe_ratio: float = 1.42,
    daily_pnl: float = 12_510.55,
    positions_count: int = 5,
) -> LivePortfolioMetrics:
    return LivePortfolioMetrics(
        snapshot_time=datetime(2026, 5, 22, tzinfo=UTC),
        total_value=total_value,
        cash_balance=cash_balance,
        daily_return=daily_return,
        cumulative_return=cumulative_return,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        daily_pnl=daily_pnl,
        positions_count=positions_count,
    )


def _equity_series(values: list[float], start: str = "2026-05-18") -> pd.Series:
    idx = pd.date_range(start=start, periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx, name="equity")


class TestSeriesConversion:
    def test_empty_series_returns_empty_list(self) -> None:
        assert _series_to_equity_curve(pd.Series(dtype="float64")) == []

    def test_basic_conversion_is_sorted_and_stringified(self) -> None:
        series = _equity_series([100.0, 101.5, 99.75])
        curve = _series_to_equity_curve(series)
        assert curve == [
            {"date": "2026-05-18", "value": "100.0000"},
            {"date": "2026-05-19", "value": "101.5000"},
            {"date": "2026-05-20", "value": "99.7500"},
        ]

    def test_naive_index_is_assumed_utc(self) -> None:
        naive_idx = pd.date_range("2026-05-18", periods=2, freq="D")
        series = pd.Series([1.0, 2.0], index=naive_idx)
        curve = _series_to_equity_curve(series)
        assert [p["date"] for p in curve] == ["2026-05-18", "2026-05-19"]

    def test_multi_timestamp_same_day_keeps_last(self) -> None:
        idx = pd.DatetimeIndex(
            [
                pd.Timestamp("2026-05-18T08:00", tz="UTC"),
                pd.Timestamp("2026-05-18T16:00", tz="UTC"),
            ]
        )
        series = pd.Series([100.0, 105.0], index=idx)
        curve = _series_to_equity_curve(series)
        assert curve == [{"date": "2026-05-18", "value": "105.0000"}]


def _stub_report(serialized: dict[str, object]) -> Mock:
    """Return a Mock that quacks like a StrategyReport for ``model_dump``."""

    report = Mock()
    report.model_dump.return_value = serialized
    return report


class TestPayloadBuilder:
    def test_minimum_payload_shape(self) -> None:
        payload = build_ingestion_payload(
            strategy_id="csm-set",
            strategy_type=DEFAULT_STRATEGY_TYPE,
            last_updated=datetime(2026, 5, 22, tzinfo=UTC),
            live_metrics=_metrics(),
            equity_curve=_equity_series([1_000_000.0, 1_012_510.0]),
        )

        assert set(payload.keys()) == {
            "strategy_metadata",
            "performance_metrics",
            "current_exposure",
            "extended_data",
        }
        assert payload["strategy_metadata"] == {
            "id": "csm-set",
            "type": "EQUITY_MOMENTUM",
            "last_updated": "2026-05-22T00:00:00+00:00",
        }
        assert payload["performance_metrics"]["daily_pnl"] == "12510.5500"
        assert payload["performance_metrics"]["max_drawdown"] == "-0.0460"
        assert payload["performance_metrics"]["sharpe_ratio"] == "1.4200"
        assert len(payload["performance_metrics"]["equity_curve"]) == 2
        assert payload["current_exposure"] == {
            "total_value": "1000000.0000",
            "cash_balance": "50000.0000",
            "positions_count": 5,
        }
        assert payload["extended_data"] == {}

    def test_naive_last_updated_is_coerced_to_utc(self) -> None:
        payload = build_ingestion_payload(
            strategy_id="csm-set",
            strategy_type=DEFAULT_STRATEGY_TYPE,
            last_updated=datetime(2026, 5, 22, 9, 30),
            live_metrics=_metrics(),
            equity_curve=_equity_series([1.0]),
        )
        assert payload["strategy_metadata"]["last_updated"].endswith("+00:00")

    def test_empty_equity_curve_fallback_one_point(self) -> None:
        payload = build_ingestion_payload(
            strategy_id="csm-set",
            strategy_type=DEFAULT_STRATEGY_TYPE,
            last_updated=datetime(2026, 5, 22, tzinfo=UTC),
            live_metrics=_metrics(total_value=987_654.0),
            equity_curve=pd.Series(dtype="float64"),
        )
        curve = payload["performance_metrics"]["equity_curve"]
        assert curve == [{"date": "2026-05-22", "value": "987654.0000"}]

    def test_report_lands_under_extended_data(self) -> None:
        serialised: dict[str, object] = {"currency": "THB", "headline": {"total_trades": 10}}
        report = _stub_report(serialised)
        payload = build_ingestion_payload(
            strategy_id="csm-set",
            strategy_type=DEFAULT_STRATEGY_TYPE,
            last_updated=datetime(2026, 5, 22, tzinfo=UTC),
            live_metrics=_metrics(),
            equity_curve=_equity_series([1.0]),
            report=report,
        )
        report.model_dump.assert_called_once_with(mode="json")
        assert payload["extended_data"]["report"] == serialised
