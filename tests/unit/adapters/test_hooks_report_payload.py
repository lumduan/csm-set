"""Unit tests for the strategy-report payload path in :func:`run_post_refresh_hook`."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from csm.adapters import AdapterManager
from csm.adapters.hooks import run_post_refresh_hook
from csm.data.store import ParquetStore


def _make_gw() -> AsyncMock:
    gw: AsyncMock = AsyncMock()
    gw.write_daily_performance = AsyncMock()
    gw.write_portfolio_snapshot = AsyncMock()
    return gw


def _make_pg() -> AsyncMock:
    pg: AsyncMock = AsyncMock()
    pg.write_equity_curve = AsyncMock(return_value=10)
    pg.write_trade_history = AsyncMock(return_value=0)
    return pg


def _make_prices() -> pd.DataFrame:
    idx: pd.DatetimeIndex = pd.date_range("2026-05-01", periods=5, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "SET:DELTA": [319.0, 320.0, 321.0, 322.0, 323.0],
            "SET:IRPC": [2.30, 2.32, 2.33, 2.34, 2.35],
            "^SET.BK": [1500.0, 1510.0, 1515.0, 1520.0, 1525.0],
        },
        index=idx,
    )


def _make_store(prices: pd.DataFrame) -> MagicMock:
    store: MagicMock = MagicMock(spec=ParquetStore)
    store.load.side_effect = lambda key: prices if key == "prices_latest" else pd.DataFrame()
    return store


def _write_yaml(tmp_path: Path) -> Path:
    yaml_text: str = textwrap.dedent(
        """
        strategy_id: csm-set
        entry_date: "2026-05-01"
        starting_nav: 1000000.0
        cash: 37699.71
        positions:
          - {symbol: DELTA, shares: 300, avg_cost: 319.51}
          - {symbol: SET:IRPC, shares: 56600, avg_cost: 2.30}
        """
    ).strip()
    path: Path = tmp_path / "live_portfolio.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_daily_performance_payload_includes_extended_data_report(
    tmp_path: Path,
) -> None:
    gw: AsyncMock = _make_gw()
    pg: AsyncMock = _make_pg()
    manager: AdapterManager = AdapterManager(postgres=pg, gateway=gw, mongo=None)
    prices: pd.DataFrame = _make_prices()
    store: MagicMock = _make_store(prices)
    live_path: Path = _write_yaml(tmp_path)

    await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

    gw.write_daily_performance.assert_called_once()
    metrics: dict = gw.write_daily_performance.call_args[0][2]
    assert "extended_data" in metrics
    assert "report" in metrics["extended_data"]
    report_dict: dict = metrics["extended_data"]["report"]
    assert "headline" in report_dict
    assert "risk_adjusted" in report_dict
    # Decimal-as-string contract
    assert isinstance(report_dict["initial_capital"], str)


@pytest.mark.asyncio
async def test_daily_performance_payload_omits_report_when_no_prices(
    tmp_path: Path,
) -> None:
    gw: AsyncMock = _make_gw()
    pg: AsyncMock = _make_pg()
    manager: AdapterManager = AdapterManager(postgres=pg, gateway=gw, mongo=None)
    # Empty prices → live_metrics is None → no report
    store: MagicMock = _make_store(pd.DataFrame())
    live_path: Path = _write_yaml(tmp_path)

    await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

    gw.write_daily_performance.assert_not_called()


@pytest.mark.asyncio
async def test_daily_performance_payload_omits_benchmark_when_column_missing(
    tmp_path: Path,
) -> None:
    """When ``^SET.BK`` is absent from prices_latest, the report still ships,
    just with no benchmark_comparison/benchmark_equity_curve."""
    gw: AsyncMock = _make_gw()
    pg: AsyncMock = _make_pg()
    manager: AdapterManager = AdapterManager(postgres=pg, gateway=gw, mongo=None)
    prices: pd.DataFrame = _make_prices().drop(columns=["^SET.BK"])
    store: MagicMock = _make_store(prices)
    live_path: Path = _write_yaml(tmp_path)

    await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)
    gw.write_daily_performance.assert_called_once()
    report: dict = gw.write_daily_performance.call_args[0][2]["extended_data"]["report"]
    assert report.get("benchmark_comparison") is None
    assert report.get("benchmark_equity_curve") == []
