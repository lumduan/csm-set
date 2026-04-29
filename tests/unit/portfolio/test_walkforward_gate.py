"""Unit tests for WalkForwardGate validation module."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from csm.portfolio.walkforward_gate import (
    FoldGateResult,
    WalkForwardGate,
    WalkForwardGateConfig,
    WalkForwardGateResult,
)

# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def gate() -> WalkForwardGate:
    return WalkForwardGate()


@pytest.fixture
def default_config() -> WalkForwardGateConfig:
    return WalkForwardGateConfig()


@pytest.fixture
def all_pass_metrics() -> list[dict[str, object]]:
    """5 folds, all with healthy positive OOS Sharpe."""
    return [
        {
            "fold": f + 1,
            "oos_sharpe": 0.65 + 0.05 * f,
            "oos_cagr": 0.10 + 0.01 * f,
            "oos_max_dd": -0.20 + 0.01 * f,
            "train_start": "2010-01-01",
            "train_end": f"201{5 + f}-12-31",
            "test_start": f"201{6 + f}-01-01",
            "test_end": f"201{6 + f}-12-31",
        }
        for f in range(5)
    ]


@pytest.fixture
def mixed_fail_metrics() -> list[dict[str, object]]:
    """5 folds, fold 3 has negative OOS Sharpe."""
    return [
        {
            "fold": 1,
            "oos_sharpe": 0.70,
            "oos_cagr": 0.11,
            "oos_max_dd": -0.18,
        },
        {
            "fold": 2,
            "oos_sharpe": 0.55,
            "oos_cagr": 0.08,
            "oos_max_dd": -0.22,
        },
        {
            "fold": 3,
            "oos_sharpe": -0.15,
            "oos_cagr": -0.02,
            "oos_max_dd": -0.35,
        },
        {
            "fold": 4,
            "oos_sharpe": 0.60,
            "oos_cagr": 0.09,
            "oos_max_dd": -0.19,
        },
        {
            "fold": 5,
            "oos_sharpe": 0.72,
            "oos_cagr": 0.12,
            "oos_max_dd": -0.15,
        },
    ]


@pytest.fixture
def all_fail_metrics() -> list[dict[str, object]]:
    """3 folds, all negative OOS Sharpe."""
    return [
        {"fold": 1, "oos_sharpe": -0.30, "oos_cagr": -0.05, "oos_max_dd": -0.40},
        {"fold": 2, "oos_sharpe": -0.10, "oos_cagr": -0.02, "oos_max_dd": -0.30},
        {"fold": 3, "oos_sharpe": -0.45, "oos_cagr": -0.08, "oos_max_dd": -0.50},
    ]


@pytest.fixture
def is_metrics() -> dict[str, float]:
    return {"sharpe": 0.85, "cagr": 0.13, "max_drawdown": -0.22}


@pytest.fixture
def aggregate_oos() -> dict[str, float]:
    return {"sharpe": 0.68, "cagr": 0.10, "max_drawdown": -0.20}


# ── TestWalkForwardGateConfig ────────────────────────────────────────────────


class TestWalkForwardGateConfig:
    """Pydantic model validation for WalkForwardGateConfig."""

    def test_defaults(self) -> None:
        c = WalkForwardGateConfig()
        assert c.enabled is True
        assert c.min_oos_sharpe == 0.0
        assert c.max_is_oos_sharpe_ratio == 1.5
        assert c.require_all_folds_positive_sharpe is True
        assert c.min_folds_required == 5

    def test_custom_values(self) -> None:
        c = WalkForwardGateConfig(
            min_oos_sharpe=0.1,
            max_is_oos_sharpe_ratio=2.0,
            require_all_folds_positive_sharpe=False,
            min_folds_required=3,
        )
        assert c.min_oos_sharpe == 0.1
        assert c.max_is_oos_sharpe_ratio == 2.0
        assert c.require_all_folds_positive_sharpe is False
        assert c.min_folds_required == 3

    def test_min_oos_sharpe_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            WalkForwardGateConfig(min_oos_sharpe=15.0)

    def test_max_ratio_must_be_gt_1(self) -> None:
        with pytest.raises(ValidationError):
            WalkForwardGateConfig(max_is_oos_sharpe_ratio=0.5)

    def test_min_folds_required_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            WalkForwardGateConfig(min_folds_required=0)


# ── TestWalkForwardGateResult ────────────────────────────────────────────────


class TestWalkForwardGateResult:
    """Pydantic model construction for WalkForwardGateResult."""

    def test_passed_result(self) -> None:
        r = WalkForwardGateResult(
            passed=True,
            n_folds=5,
            n_folds_passing=5,
            fold_results=[],
            aggregate_oos_sharpe=0.72,
        )
        assert r.passed is True
        assert r.n_folds == 5
        assert r.n_folds_passing == 5
        assert r.failures == []

    def test_failed_result_with_failures(self) -> None:
        r = WalkForwardGateResult(
            passed=False,
            n_folds=5,
            n_folds_passing=3,
            fold_results=[],
            aggregate_oos_sharpe=0.45,
            failures=["Fold 3: OOS Sharpe -0.15 ≤ min 0.00"],
        )
        assert r.passed is False
        assert len(r.failures) == 1

    def test_default_failures_empty(self) -> None:
        r = WalkForwardGateResult(
            passed=True,
            n_folds=5,
            n_folds_passing=5,
            fold_results=[],
            aggregate_oos_sharpe=0.0,
        )
        assert r.failures == []


# ── TestFoldGateResult ───────────────────────────────────────────────────────


class TestFoldGateResult:
    """Pydantic model construction for FoldGateResult."""

    def test_passing_fold(self) -> None:
        fr = FoldGateResult(
            fold=1,
            oos_sharpe=0.75,
            oos_sharpe_pass=True,
            is_oos_ratio_pass=True,
        )
        assert fr.fold == 1
        assert fr.oos_sharpe == 0.75
        assert fr.oos_sharpe_pass is True
        assert fr.is_oos_ratio_pass is True
        assert fr.oos_cagr is None
        assert fr.oos_max_dd is None

    def test_failing_fold(self) -> None:
        fr = FoldGateResult(
            fold=3,
            oos_sharpe=-0.20,
            oos_cagr=-0.03,
            oos_max_dd=-0.40,
            oos_sharpe_pass=False,
            is_oos_ratio_pass=False,
        )
        assert fr.oos_sharpe_pass is False
        assert fr.is_oos_ratio_pass is False
        assert fr.oos_cagr == -0.03
        assert fr.oos_max_dd == -0.40

    def test_optional_date_fields(self) -> None:
        fr = FoldGateResult(
            fold=1,
            oos_sharpe=0.70,
            oos_sharpe_pass=True,
            is_oos_ratio_pass=True,
            train_start="2010-01-01",
            train_end="2015-12-31",
            test_start="2016-01-01",
            test_end="2016-12-31",
        )
        assert fr.train_start == "2010-01-01"
        assert fr.test_end == "2016-12-31"


# ── TestWalkForwardGate ──────────────────────────────────────────────────────


class TestWalkForwardGate:
    """Core behaviour tests for WalkForwardGate.validate()."""

    def test_disabled_pass_through(
        self,
        gate: WalkForwardGate,
        all_fail_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
    ) -> None:
        config = WalkForwardGateConfig(enabled=False)
        result = gate.validate(all_fail_metrics, aggregate_oos, config=config)
        assert result.passed is True
        assert result.n_folds == len(all_fail_metrics)

    def test_all_folds_pass(
        self,
        gate: WalkForwardGate,
        all_pass_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
        is_metrics: dict[str, float],
    ) -> None:
        result = gate.validate(all_pass_metrics, aggregate_oos, is_metrics)
        assert result.passed is True
        assert result.n_folds == 5
        assert result.n_folds_passing == 5
        assert len(result.failures) == 0
        assert result.is_sharpe == 0.85
        assert result.is_oos_sharpe_ratio == pytest.approx(0.85 / 0.68)

    def test_mixed_folds_some_fail(
        self,
        gate: WalkForwardGate,
        mixed_fail_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
    ) -> None:
        result = gate.validate(mixed_fail_metrics, aggregate_oos)
        assert result.passed is False
        assert result.n_folds == 5
        assert result.n_folds_passing == 4

    def test_all_folds_fail(
        self,
        gate: WalkForwardGate,
        all_fail_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
    ) -> None:
        result = gate.validate(all_fail_metrics, aggregate_oos)
        assert result.passed is False
        assert result.n_folds_passing == 0

    def test_insufficient_folds(
        self,
        gate: WalkForwardGate,
        all_fail_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
    ) -> None:
        config = WalkForwardGateConfig(min_folds_required=10)
        result = gate.validate(all_fail_metrics, aggregate_oos, config=config)
        assert result.passed is False
        assert any("Insufficient folds" in f for f in result.failures)

    def test_empty_fold_list(
        self,
        gate: WalkForwardGate,
        aggregate_oos: dict[str, float],
    ) -> None:
        result = gate.validate([], aggregate_oos)
        assert result.passed is False
        assert result.n_folds == 0
        assert result.n_folds_passing == 0

    def test_single_fold_insufficient(
        self,
        gate: WalkForwardGate,
        aggregate_oos: dict[str, float],
    ) -> None:
        single = [{"fold": 1, "oos_sharpe": 0.80}]
        result = gate.validate(single, aggregate_oos)
        assert result.passed is False
        assert result.n_folds == 1
        assert any("Insufficient folds" in f for f in result.failures)

    def test_is_oos_ratio_exceeds_max(
        self,
        gate: WalkForwardGate,
        all_pass_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
    ) -> None:
        is_metrics = {"sharpe": 1.8}
        config = WalkForwardGateConfig(max_is_oos_sharpe_ratio=1.5)
        result = gate.validate(all_pass_metrics, aggregate_oos, is_metrics, config=config)
        assert result.passed is False
        assert any("IS/OOS Sharpe ratio" in f for f in result.failures)

    def test_is_metrics_none_skips_ratio_check(
        self,
        gate: WalkForwardGate,
        all_pass_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
    ) -> None:
        result = gate.validate(all_pass_metrics, aggregate_oos, is_metrics=None)
        assert result.passed is True
        assert result.is_sharpe is None
        assert result.is_oos_sharpe_ratio is None

    def test_missing_optional_keys_handled(
        self,
        gate: WalkForwardGate,
        aggregate_oos: dict[str, float],
    ) -> None:
        minimal = [
            {"fold": 1, "oos_sharpe": 0.55},
            {"fold": 2, "oos_sharpe": 0.60},
            {"fold": 3, "oos_sharpe": 0.50},
            {"fold": 4, "oos_sharpe": 0.65},
            {"fold": 5, "oos_sharpe": 0.70},
        ]
        result = gate.validate(minimal, aggregate_oos)
        assert result.passed is True
        for fr in result.fold_results:
            assert fr.oos_cagr is None
            assert fr.oos_max_dd is None

    def test_missing_sharpe_key_treated_as_zero(
        self,
        gate: WalkForwardGate,
        aggregate_oos: dict[str, float],
    ) -> None:
        missing_sharpe = [
            {"fold": 1},
            {"fold": 2},
            {"fold": 3},
            {"fold": 4},
            {"fold": 5},
        ]
        result = gate.validate(missing_sharpe, aggregate_oos)
        assert result.passed is False

    def test_determinism(
        self,
        gate: WalkForwardGate,
        all_pass_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
        is_metrics: dict[str, float],
    ) -> None:
        r1 = gate.validate(all_pass_metrics, aggregate_oos, is_metrics)
        r2 = gate.validate(all_pass_metrics, aggregate_oos, is_metrics)
        assert r1.passed == r2.passed
        assert r1.n_folds_passing == r2.n_folds_passing
        assert r1.failures == r2.failures

    def test_default_config_used_when_none(
        self,
        gate: WalkForwardGate,
        all_pass_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
    ) -> None:
        result = gate.validate(all_pass_metrics, aggregate_oos, config=None)
        assert isinstance(result, WalkForwardGateResult)

    def test_require_all_folds_false_allows_mixed(
        self,
        gate: WalkForwardGate,
        mixed_fail_metrics: list[dict[str, object]],
        aggregate_oos: dict[str, float],
    ) -> None:
        config = WalkForwardGateConfig(
            min_oos_sharpe=-0.30,
            require_all_folds_positive_sharpe=False,
            min_folds_required=3,
        )
        result = gate.validate(mixed_fail_metrics, aggregate_oos, config=config)
        assert result.passed is True
