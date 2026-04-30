"""Walk-forward validation gate.

A stateless utility that validates walk-forward backtest results against
configurable pass/fail criteria.  Accepts generic fold-metrics dicts so that
``csm.portfolio`` remains free of an upward dependency on ``csm.research``.
"""

from __future__ import annotations

import logging
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

logger: logging.Logger = logging.getLogger(__name__)


class WalkForwardGateConfig(BaseModel):
    """Configuration for the walk-forward validation gate.

    Defines the pass/fail thresholds applied to each fold and to the
    aggregate in-sample vs out-of-sample comparison.
    """

    enabled: bool = Field(default=True)
    min_oos_sharpe: float = Field(default=0.0, ge=-10.0, le=10.0)
    max_is_oos_sharpe_ratio: float = Field(default=1.5, gt=1.0, le=100.0)
    require_all_folds_positive_sharpe: bool = Field(default=True)
    min_folds_required: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def _validate_folds_required(self) -> Self:
        if self.min_folds_required < 1:
            raise ValueError("min_folds_required must be >= 1")
        return self


class FoldGateResult(BaseModel):
    """Per-fold validation result from the walk-forward gate."""

    fold: int
    oos_sharpe: float
    oos_cagr: float | None = None
    oos_max_dd: float | None = None
    oos_sharpe_pass: bool
    is_oos_ratio_pass: bool
    train_start: str | None = None
    train_end: str | None = None
    test_start: str | None = None
    test_end: str | None = None


class WalkForwardGateResult(BaseModel):
    """Aggregate result of walk-forward gate validation."""

    passed: bool
    n_folds: int
    n_folds_passing: int
    fold_results: list[FoldGateResult]
    aggregate_oos_sharpe: float
    is_sharpe: float | None = None
    is_oos_sharpe_ratio: float | None = None
    failures: list[str] = Field(default_factory=list)


class WalkForwardGate:
    """Stateless validation gate for walk-forward backtest results.

    Validates each fold's OOS Sharpe against a minimum threshold, checks
    that the IS/OOS Sharpe ratio does not exceed the configured ceiling
    (indicating overfitting), and enforces a minimum number of passing
    folds.

    Usage::

        gate = WalkForwardGate()
        result = gate.validate(
            fold_metrics=wf_result.folds,
            aggregate_oos_metrics=wf_result.aggregate_oos_metrics,
            is_metrics=wf_result.is_metrics,
        )
        if not result.passed:
            print(result.failures)
    """

    def validate(
        self,
        fold_metrics: list[dict[str, Any]],
        aggregate_oos_metrics: dict[str, float],
        is_metrics: dict[str, float] | None = None,
        config: WalkForwardGateConfig | None = None,
    ) -> WalkForwardGateResult:
        """Validate walk-forward fold results against the gate criteria.

        Args:
            fold_metrics: Per-fold metrics dicts.  Each dict must contain at
                least the key ``"oos_sharpe"`` (float).  Optional keys:
                ``"oos_cagr"``, ``"oos_max_dd"``, ``"train_start"``,
                ``"train_end"``, ``"test_start"``, ``"test_end"``.
            aggregate_oos_metrics: Aggregate OOS metrics across all folds.
                Must contain key ``"sharpe"``.
            is_metrics: In-sample metrics from the full-period backtest.
                Must contain key ``"sharpe"`` when *config* requires the
                IS/OOS ratio check.  ``None`` skips the ratio check.
            config: Gate configuration.  Uses :class:`WalkForwardGateConfig`
                defaults when ``None``.

        Returns:
            :class:`WalkForwardGateResult` with overall pass/fail verdict,
            per-fold details, and a human-readable failures list.
        """
        if config is None:
            config = WalkForwardGateConfig()

        if not config.enabled:
            return WalkForwardGateResult(
                passed=True,
                n_folds=len(fold_metrics),
                n_folds_passing=len(fold_metrics),
                fold_results=[],
                aggregate_oos_sharpe=aggregate_oos_metrics.get("sharpe", 0.0),
            )

        is_sharpe: float | None = None
        if is_metrics is not None:
            is_sharpe = is_metrics.get("sharpe")

        aggregate_oos_sharpe: float = aggregate_oos_metrics.get("sharpe", 0.0)
        is_oos_sharpe_ratio: float | None = None
        if is_sharpe is not None and aggregate_oos_sharpe > 0:
            is_oos_sharpe_ratio = is_sharpe / aggregate_oos_sharpe

        fold_results: list[FoldGateResult] = []
        failures: list[str] = []
        n_passing: int = 0

        for i, fm in enumerate(fold_metrics):
            oos_sharpe: float = float(fm.get("oos_sharpe", 0.0))
            fold: int = int(fm.get("fold", i + 1))

            oos_sharpe_pass: bool = bool(oos_sharpe > config.min_oos_sharpe)

            # Per-fold IS/OOS ratio only checkable when is_sharpe is available
            is_oos_ratio_pass: bool = True
            if is_sharpe is not None and oos_sharpe > 0:
                fold_ratio: float = is_sharpe / oos_sharpe
                is_oos_ratio_pass = bool(fold_ratio <= config.max_is_oos_sharpe_ratio)
            elif config.require_all_folds_positive_sharpe and oos_sharpe <= 0:
                is_oos_ratio_pass = False

            fold_pass: bool = bool(oos_sharpe_pass and is_oos_ratio_pass)
            if fold_pass:
                n_passing += 1

            if not oos_sharpe_pass:
                failures.append(
                    f"Fold {fold}: OOS Sharpe {oos_sharpe:.4f} ≤ min {config.min_oos_sharpe:.4f}"
                )
            if not is_oos_ratio_pass and is_sharpe is not None and oos_sharpe > 0:
                fold_ratio = is_sharpe / oos_sharpe
                failures.append(
                    f"Fold {fold}: IS/OOS Sharpe ratio {fold_ratio:.2f} > "
                    f"max {config.max_is_oos_sharpe_ratio:.2f}"
                )

            fold_results.append(
                FoldGateResult(
                    fold=fold,
                    oos_sharpe=oos_sharpe,
                    oos_cagr=float(fm["oos_cagr"])
                    if "oos_cagr" in fm and fm["oos_cagr"] is not None
                    else None,
                    oos_max_dd=float(fm["oos_max_dd"])
                    if "oos_max_dd" in fm and fm["oos_max_dd"] is not None
                    else None,
                    oos_sharpe_pass=oos_sharpe_pass,
                    is_oos_ratio_pass=is_oos_ratio_pass,
                    train_start=str(fm["train_start"])
                    if "train_start" in fm and fm["train_start"] is not None
                    else None,
                    train_end=str(fm["train_end"])
                    if "train_end" in fm and fm["train_end"] is not None
                    else None,
                    test_start=str(fm["test_start"])
                    if "test_start" in fm and fm["test_start"] is not None
                    else None,
                    test_end=str(fm["test_end"])
                    if "test_end" in fm and fm["test_end"] is not None
                    else None,
                )
            )

        # Aggregate checks
        if len(fold_metrics) < config.min_folds_required:
            failures.append(
                f"Insufficient folds: {len(fold_metrics)} < min {config.min_folds_required}"
            )

        if config.require_all_folds_positive_sharpe and n_passing < len(fold_metrics):
            failures.append("Not all folds have positive OOS Sharpe")

        if is_oos_sharpe_ratio is not None and is_oos_sharpe_ratio > config.max_is_oos_sharpe_ratio:
            failures.append(
                f"Aggregate IS/OOS Sharpe ratio {is_oos_sharpe_ratio:.2f} > "
                f"max {config.max_is_oos_sharpe_ratio:.2f}"
            )

        passed: bool = len(failures) == 0

        return WalkForwardGateResult(
            passed=passed,
            n_folds=len(fold_metrics),
            n_folds_passing=n_passing,
            fold_results=fold_results,
            aggregate_oos_sharpe=aggregate_oos_sharpe,
            is_sharpe=is_sharpe,
            is_oos_sharpe_ratio=is_oos_sharpe_ratio,
            failures=failures,
        )


__all__: list[str] = [
    "FoldGateResult",
    "WalkForwardGate",
    "WalkForwardGateConfig",
    "WalkForwardGateResult",
]
