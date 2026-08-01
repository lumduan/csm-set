"""Unit tests for the strategy-report payload path in :func:`run_post_refresh_hook`."""

from __future__ import annotations

import textwrap
from datetime import datetime, time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from csm.adapters import AdapterManager
from csm.adapters.hooks import run_post_refresh_hook
from csm.data.store import ParquetStore

_BKK: ZoneInfo = ZoneInfo("Asia/Bangkok")


def _make_gateway_client() -> AsyncMock:
    gc: AsyncMock = AsyncMock()
    gc.post_daily_report = AsyncMock()
    return gc


def _make_pg() -> AsyncMock:
    pg: AsyncMock = AsyncMock()
    pg.write_equity_curve = AsyncMock(return_value=10)
    pg.write_trade_history = AsyncMock(return_value=0)
    return pg


def _make_prices() -> pd.DataFrame:
    """5 daily bars ending **today** (Bangkok), 09:55 as in production.

    The dates must be now-relative: the hook only POSTs a daily report when the
    latest bar is today's, so a fixed historical base would be treated as a market
    closure and skipped. See ``run_post_refresh_hook``'s "no fresh bar, no gateway
    write" contract.
    """
    last_bar: pd.Timestamp = pd.Timestamp(
        datetime.combine(datetime.now(_BKK).date(), time(9, 55), tzinfo=_BKK)
    )
    idx: pd.DatetimeIndex = pd.DatetimeIndex(
        [last_bar - pd.Timedelta(days=4 - i) for i in range(5)]
    )
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
    # entry_date must sit at/below the first bar of the now-relative panel from
    # _make_prices, otherwise the repriced window is empty and no metrics compute.
    entry: str = (datetime.now(_BKK).date() - pd.Timedelta(days=4)).isoformat()
    yaml_text: str = textwrap.dedent(
        f"""
        strategy_id: csm-set
        entry_date: "{entry}"
        starting_nav: 1000000.0
        cash: 37699.71
        positions:
          - {{symbol: DELTA, shares: 300, avg_cost: 319.51}}
          - {{symbol: SET:IRPC, shares: 56600, avg_cost: 2.30}}
        """
    ).strip()
    path: Path = tmp_path / "live_portfolio.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_daily_report_payload_includes_extended_data_report(
    tmp_path: Path,
) -> None:
    gc: AsyncMock = _make_gateway_client()
    pg: AsyncMock = _make_pg()
    manager: AdapterManager = AdapterManager(postgres=pg, gateway_client=gc, mongo=None)
    prices: pd.DataFrame = _make_prices()
    store: MagicMock = _make_store(prices)
    live_path: Path = _write_yaml(tmp_path)

    await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

    gc.post_daily_report.assert_called_once()
    payload: dict[str, Any] = gc.post_daily_report.call_args[0][0]
    assert "extended_data" in payload
    assert "report" in payload["extended_data"]
    report_dict: dict[str, Any] = payload["extended_data"]["report"]
    assert "headline" in report_dict
    assert "risk_adjusted" in report_dict
    # Decimal-as-string contract
    assert isinstance(report_dict["initial_capital"], str)


@pytest.mark.asyncio
async def test_daily_report_payload_omits_when_no_prices(tmp_path: Path) -> None:
    gc: AsyncMock = _make_gateway_client()
    pg: AsyncMock = _make_pg()
    manager: AdapterManager = AdapterManager(postgres=pg, gateway_client=gc, mongo=None)
    # Empty prices → live_metrics is None → no POST
    store: MagicMock = _make_store(pd.DataFrame())
    live_path: Path = _write_yaml(tmp_path)

    await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

    gc.post_daily_report.assert_not_called()


@pytest.mark.asyncio
async def test_daily_report_payload_omits_benchmark_when_column_missing(
    tmp_path: Path,
) -> None:
    """When ``^SET.BK`` is absent from prices_latest, the report still ships,
    just with no benchmark_comparison/benchmark_equity_curve."""
    gc: AsyncMock = _make_gateway_client()
    pg: AsyncMock = _make_pg()
    manager: AdapterManager = AdapterManager(postgres=pg, gateway_client=gc, mongo=None)
    prices: pd.DataFrame = _make_prices().drop(columns=["^SET.BK"])
    store: MagicMock = _make_store(prices)
    live_path: Path = _write_yaml(tmp_path)

    await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)
    gc.post_daily_report.assert_called_once()
    report: dict[str, Any] = gc.post_daily_report.call_args[0][0]["extended_data"]["report"]
    assert report.get("benchmark_comparison") is None
    assert report.get("benchmark_equity_curve") == []
