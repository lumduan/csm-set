"""Unit tests for ``csm.live.portfolio``."""

from __future__ import annotations

import math
import textwrap
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from csm.live.portfolio import (
    LivePortfolioConfig,
    LivePortfolioMetrics,
    LivePosition,
    compute_live_portfolio_metrics,
    load_live_portfolio,
)
from csm.research.strategy_report import build_strategy_report


@pytest.fixture()
def live_yaml(tmp_path: Path) -> Path:
    """Write a representative live-portfolio config and return its path."""
    text: str = textwrap.dedent(
        """
        strategy_id: csm-set
        entry_date: "2026-05-05"
        starting_nav: 1000000.0
        cash: 37699.71
        positions:
          - {symbol: DELTA, shares: 300, avg_cost: 319.51}
          - {symbol: SET:IRPC, shares: 56600, avg_cost: 2.30}
        """
    ).strip()
    path: Path = tmp_path / "live_portfolio.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadLivePortfolio:
    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert load_live_portfolio(tmp_path / "absent.yaml") is None

    def test_parses_fields_and_prefixes_symbols(self, live_yaml: Path) -> None:
        cfg: LivePortfolioConfig | None = load_live_portfolio(live_yaml)
        assert cfg is not None
        assert cfg.strategy_id == "csm-set"
        assert cfg.starting_nav == 1_000_000.0
        assert cfg.cash == 37_699.71
        assert len(cfg.positions) == 2
        assert cfg.positions[0].qualified_symbol == "SET:DELTA"
        assert cfg.positions[1].qualified_symbol == "SET:IRPC"

    def test_rejects_empty_positions(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "empty_positions.yaml"
        path.write_text(
            textwrap.dedent(
                """
                strategy_id: csm-set
                entry_date: "2026-05-05"
                starting_nav: 1000000.0
                cash: 0.0
                positions: []
                """
            ).strip(),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="at least one position"):
            load_live_portfolio(path)

    def test_rejects_missing_required_keys(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "incomplete.yaml"
        path.write_text(
            'strategy_id: csm-set\nentry_date: "2026-05-05"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing required keys"):
            load_live_portfolio(path)


def _make_prices(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    """Build a small 2-symbol price panel; each row is (date, delta_close, irpc_close)."""
    index: pd.DatetimeIndex = pd.DatetimeIndex(
        [pd.Timestamp(r[0], tz="Asia/Bangkok") for r in rows]
    )
    data: dict[str, list[float]] = {
        "SET:DELTA": [r[1] for r in rows],
        "SET:IRPC": [r[2] for r in rows],
    }
    return pd.DataFrame(data, index=index)


class TestComputeLivePortfolioMetrics:
    @pytest.fixture()
    def cfg(self) -> LivePortfolioConfig:
        return LivePortfolioConfig(
            strategy_id="csm-set",
            entry_date=pd.Timestamp("2026-05-05").date(),
            starting_nav=1_000_000.0,
            cash=37_699.71,
            positions=(
                LivePosition(symbol="DELTA", shares=300.0, avg_cost=319.51),
                LivePosition(symbol="SET:IRPC", shares=56_600.0, avg_cost=2.30),
            ),
        )

    def test_returns_none_when_prices_empty(self, cfg: LivePortfolioConfig) -> None:
        assert compute_live_portfolio_metrics(cfg, pd.DataFrame()) is None

    def test_returns_none_when_required_symbol_missing(self, cfg: LivePortfolioConfig) -> None:
        prices: pd.DataFrame = pd.DataFrame(
            {"SET:DELTA": [319.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-05-05", tz="Asia/Bangkok")]),
        )
        assert compute_live_portfolio_metrics(cfg, prices) is None

    def test_filters_to_entry_date_onward(self, cfg: LivePortfolioConfig) -> None:
        prices: pd.DataFrame = _make_prices(
            [
                ("2026-05-01", 319.0, 2.30),  # before entry — ignored
                ("2026-05-05", 319.5, 2.30),
                ("2026-05-06", 320.0, 2.32),
            ]
        )
        m = compute_live_portfolio_metrics(cfg, prices)
        assert m is not None
        # NAV = 300 * 320.0 + 56600 * 2.32 + 37699.71
        expected_nav: float = 300 * 320.0 + 56_600 * 2.32 + 37_699.71
        assert math.isclose(m.total_value, expected_nav, rel_tol=1e-9)
        assert m.positions_count == 2

    def test_daily_return_and_pnl_against_previous_day(self, cfg: LivePortfolioConfig) -> None:
        prices: pd.DataFrame = _make_prices(
            [
                ("2026-05-05", 319.0, 2.30),
                ("2026-05-06", 319.0, 2.32),
            ]
        )
        m = compute_live_portfolio_metrics(cfg, prices)
        assert m is not None
        mv_prev: float = 300 * 319.0 + 56_600 * 2.30
        mv_today: float = 300 * 319.0 + 56_600 * 2.32
        assert math.isclose(m.daily_pnl, mv_today - mv_prev, rel_tol=1e-9)
        nav_prev: float = mv_prev + 37_699.71
        nav_today: float = mv_today + 37_699.71
        assert math.isclose(m.daily_return, nav_today / nav_prev - 1.0, rel_tol=1e-9)

    def test_cumulative_return_vs_starting_nav(self, cfg: LivePortfolioConfig) -> None:
        prices: pd.DataFrame = _make_prices(
            [
                ("2026-05-05", 319.0, 2.30),
                ("2026-05-06", 319.0, 2.32),
            ]
        )
        m = compute_live_portfolio_metrics(cfg, prices)
        assert m is not None
        nav_today: float = 300 * 319.0 + 56_600 * 2.32 + 37_699.71
        assert math.isclose(m.cumulative_return, nav_today / cfg.starting_nav - 1.0, rel_tol=1e-9)

    def test_max_drawdown_uses_starting_nav_anchor(self, cfg: LivePortfolioConfig) -> None:
        """The drawdown calc anchors at ``starting_nav`` so it never reports a
        positive max DD even when the curve drops on entry day."""
        prices: pd.DataFrame = _make_prices(
            [
                # Down 5% on day 1, slight recovery on day 2 — peak stays at starting_nav.
                ("2026-05-05", 280.0, 2.10),
                ("2026-05-06", 285.0, 2.12),
            ]
        )
        m = compute_live_portfolio_metrics(cfg, prices)
        assert m is not None
        assert m.max_drawdown <= 0.0

    def test_sharpe_zero_below_min_sample(self, cfg: LivePortfolioConfig) -> None:
        """Until ~6 weeks of live data we report Sharpe=0 to avoid noise."""
        prices: pd.DataFrame = _make_prices([("2026-05-05", 319.0, 2.30)])
        m = compute_live_portfolio_metrics(cfg, prices)
        assert m is not None
        assert m.sharpe_ratio == 0.0

    def test_sharpe_computed_with_sufficient_sample(self, cfg: LivePortfolioConfig) -> None:
        from csm.live.portfolio import SHARPE_MIN_SAMPLE

        rows: list[tuple[str, float, float]] = [
            (str(ts.date()), 319.0 + i * 0.01, 2.30 + i * 0.001)
            for i, ts in enumerate(
                pd.date_range("2026-05-05", periods=SHARPE_MIN_SAMPLE + 2, freq="B")
            )
        ]
        m = compute_live_portfolio_metrics(cfg, _make_prices(rows))
        assert m is not None
        assert m.sharpe_ratio != 0.0


def test_live_portfolio_metrics_as_dict_embeds_report() -> None:
    """When `report` is set via ``dataclasses.replace``, ``as_dict()`` exposes it."""
    metrics: LivePortfolioMetrics = LivePortfolioMetrics(
        snapshot_time=datetime(2026, 5, 20, tzinfo=UTC),
        total_value=1_010_000.0,
        cash_balance=37_699.71,
        daily_return=0.001,
        cumulative_return=0.01,
        max_drawdown=-0.05,
        sharpe_ratio=1.2,
        daily_pnl=1_000.0,
        positions_count=2,
    )
    assert metrics.report is None
    assert "extended_data" not in metrics.as_dict()

    equity = pd.Series(
        [1_000_000.0, 1_010_000.0],
        index=pd.date_range("2026-05-19", periods=2, freq="D", tz="UTC"),
    )
    report = build_strategy_report(
        trades=[],
        equity=equity,
        initial_capital=Decimal("1000000"),
        as_of=datetime(2026, 5, 20, tzinfo=UTC),
    )
    enriched: LivePortfolioMetrics = replace(metrics, report=report)
    payload = enriched.as_dict()
    assert "extended_data" in payload
    assert Decimal(payload["extended_data"]["report"]["headline"]["total_pnl"]) == Decimal("10000")
