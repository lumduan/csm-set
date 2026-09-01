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
    collapse_to_daily_bars,
    compute_live_portfolio_metrics,
    drop_unpriced_days,
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


# ---------------------------------------------------------------------------
# Regression: the 2026-09-01 dual-bar NAV corruption.
#
# The vendor began emitting a SECOND daily bar (10:00 BKK beside the 09:55 one)
# covering a subset of symbols, so one session arrived as two sparse rows.
# Reading the panel's last row then priced the book off whichever symbols
# carried the later stamp, and `sum(axis=1)`'s skipna=True valued the rest at
# ZERO — writing 373,561.70 against a true 1,273,881.70, and overwriting the
# banked 2026-08-31 equity_curve row with a two-symbol valuation.
#
# See docs/live-test/events/2026-09-01-dual-bar-nav-corruption.md.
# ---------------------------------------------------------------------------


def _dual_bar_panel() -> pd.DataFrame:
    """A clean day, then a day split across two COMPLEMENTARY sparse bars.

    2026-09-01 arrives as 09:55 (DELTA only) + 10:00 (IRPC only) — the shape
    that broke production. Their union is the session: DELTA 12.0, IRPC 3.0.
    """
    index: pd.DatetimeIndex = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-08-31 09:55", tz="Asia/Bangkok"),
            pd.Timestamp("2026-09-01 09:55", tz="Asia/Bangkok"),
            pd.Timestamp("2026-09-01 10:00", tz="Asia/Bangkok"),
        ]
    )
    return pd.DataFrame(
        {
            "SET:DELTA": [10.0, 12.0, float("nan")],
            "SET:IRPC": [2.0, float("nan"), 3.0],
        },
        index=index,
    )


class TestCollapseToDailyBars:
    def test_leaves_a_one_row_per_day_panel_untouched(self) -> None:
        """The common case must be a genuine no-op, not a rebuild."""
        panel: pd.DataFrame = _make_prices([("2026-08-31", 10.0, 2.0), ("2026-09-01", 12.0, 3.0)])
        out: pd.DataFrame = collapse_to_daily_bars(panel)
        pd.testing.assert_frame_equal(out, panel)

    def test_collapses_two_bars_into_their_union(self) -> None:
        out: pd.DataFrame = collapse_to_daily_bars(_dual_bar_panel())
        assert len(out) == 2, "one row per trading day"
        assert out.iloc[-1]["SET:DELTA"] == 12.0
        assert out.iloc[-1]["SET:IRPC"] == 3.0
        assert not out.isna().to_numpy().any()

    def test_overlapping_bars_take_the_later_value(self) -> None:
        """Where both bars carry a symbol they agreed in production; assert the rule anyway."""
        index: pd.DatetimeIndex = pd.DatetimeIndex(
            [
                pd.Timestamp("2026-09-01 09:55", tz="Asia/Bangkok"),
                pd.Timestamp("2026-09-01 10:00", tz="Asia/Bangkok"),
            ]
        )
        panel: pd.DataFrame = pd.DataFrame({"SET:DELTA": [12.0, 12.5]}, index=index)
        assert collapse_to_daily_bars(panel).iloc[-1]["SET:DELTA"] == 12.5

    def test_rekeys_so_the_UTC_calendar_day_is_preserved(self) -> None:
        """Re-keying to local midnight would shift every date back one day.

        Callers convert to UTC then normalize; 00:00+07 is 17:00 UTC on the
        PREVIOUS day. The day's last real bar stamp shares its UTC date, so the
        collapsed index must carry that, not midnight.
        """
        out: pd.DataFrame = collapse_to_daily_bars(_dual_bar_panel())
        utc_dates = [ts.tz_convert("UTC").normalize().date() for ts in out.index]
        assert [d.isoformat() for d in utc_dates] == ["2026-08-31", "2026-09-01"]

    def test_empty_panel_is_returned_unchanged(self) -> None:
        empty: pd.DataFrame = pd.DataFrame()
        pd.testing.assert_frame_equal(collapse_to_daily_bars(empty), empty)


class TestDropUnpricedDays:
    def test_clean_panel_is_untouched(self) -> None:
        panel: pd.DataFrame = _make_prices([("2026-08-31", 10.0, 2.0)])
        pd.testing.assert_frame_equal(drop_unpriced_days(panel, context="t"), panel)

    def test_a_day_missing_any_holding_is_dropped_not_valued_at_zero(self) -> None:
        """The whole point: an unpriced holding must not silently contribute 0."""
        panel: pd.DataFrame = _make_prices(
            [("2026-08-31", 10.0, 2.0), ("2026-09-01", float("nan"), 3.0)]
        )
        out: pd.DataFrame = drop_unpriced_days(panel, context="t")
        assert len(out) == 1
        assert out.index[0] == pd.Timestamp("2026-08-31", tz="Asia/Bangkok")

    def test_names_the_missing_symbol_in_the_log(self, caplog: pytest.LogCaptureFixture) -> None:
        panel: pd.DataFrame = _make_prices([("2026-09-01", float("nan"), 3.0)])
        with caplog.at_level("WARNING"):
            drop_unpriced_days(panel, context="unit-test-context")
        assert "SET:DELTA" in caplog.text
        assert "unit-test-context" in caplog.text


class TestDualBarRegression:
    @pytest.fixture()
    def cfg(self) -> LivePortfolioConfig:
        return LivePortfolioConfig(
            strategy_id="csm-set",
            entry_date=pd.Timestamp("2026-08-31").date(),
            starting_nav=100.0,
            cash=1.0,
            positions=(
                LivePosition(symbol="DELTA", shares=10.0, avg_cost=1.0),
                LivePosition(symbol="IRPC", shares=100.0, avg_cost=1.0),
            ),
        )

    def test_nav_is_the_union_of_the_days_bars(self, cfg: LivePortfolioConfig) -> None:
        m: LivePortfolioMetrics | None = compute_live_portfolio_metrics(cfg, _dual_bar_panel())
        assert m is not None
        # union: DELTA 10*12.0 + IRPC 100*3.0 + cash 1.0
        assert m.total_value == pytest.approx(421.0)

    def test_the_sparse_last_row_valuation_is_NOT_produced(self, cfg: LivePortfolioConfig) -> None:
        """Positive control for the bug itself.

        The old code read the 10:00 bar alone: IRPC 100*3.0 + cash = 301.0,
        DELTA silently zero. That number must be unreachable now.
        """
        m: LivePortfolioMetrics | None = compute_live_portfolio_metrics(cfg, _dual_bar_panel())
        assert m is not None
        assert m.total_value != pytest.approx(301.0)

    def test_daily_return_compares_two_DAYS_not_two_bars(self, cfg: LivePortfolioConfig) -> None:
        """`iloc[-2]` meant 'yesterday' only while one row was one day.

        With two bars per session it silently became 'earlier today', which is
        how a -141.82% daily_return reached production.
        """
        m: LivePortfolioMetrics | None = compute_live_portfolio_metrics(cfg, _dual_bar_panel())
        assert m is not None
        # 2026-08-31 NAV = 10*10.0 + 100*2.0 + 1.0 = 301.0 -> 421.0
        assert m.daily_return == pytest.approx(421.0 / 301.0 - 1.0)
        assert m.daily_pnl == pytest.approx(120.0)

    def test_snapshot_time_is_the_right_calendar_day(self, cfg: LivePortfolioConfig) -> None:
        m: LivePortfolioMetrics | None = compute_live_portfolio_metrics(cfg, _dual_bar_panel())
        assert m is not None
        assert m.snapshot_time.date().isoformat() == "2026-09-01"

    def test_fails_closed_when_no_day_can_be_fully_priced(self, cfg: LivePortfolioConfig) -> None:
        """No metrics beats wrong metrics — the hook then writes no row."""
        panel: pd.DataFrame = _make_prices([("2026-09-01", float("nan"), 3.0)])
        assert compute_live_portfolio_metrics(cfg, panel) is None
