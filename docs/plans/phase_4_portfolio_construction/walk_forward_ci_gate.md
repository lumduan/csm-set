# Walk-Forward CI Gate Specification

**Feature:** Automated walk-forward validation gate for CI/CD pipelines
**Created:** 2026-04-29
**Status:** Spec — implementation deferred to Phase 8
**Target Phase:** Phase 8 (CI/CD Integration)

---

## Overview

This document specifies the walk-forward CI gate — an automated test marker that runs full walk-forward cross-validation on every pull request and fails the CI build if OOS performance degrades or overfitting is detected.

The gate uses the `WalkForwardGate` validation utility (`src/csm/portfolio/walkforward_gate.py`) from Phase 4.8. The validation logic is already implemented and tested; the CI integration (pytest marker registration, GitHub Actions workflow) is deferred to Phase 8.

---

## pytest Marker

### Definition

```toml
# pyproject.toml — to be added in Phase 8
[tool.pytest.ini_options]
markers = [
    "walk_forward: run full walk-forward OOS validation (CI gate)",
]
```

### Usage

```bash
pytest -m walk_forward -v
```

The marker should be applied to a single test function that:

1. Loads the full feature panel and price data from `ParquetStore`
2. Configures `WalkForwardAnalyzer` with `WalkForwardConfig(n_folds=5, test_years=1, min_train_years=5)`
3. Runs the walk-forward analysis with the full Phase 4 overlay stack
4. Validates results via `WalkForwardGate.validate()`
5. Asserts `result.passed is True`

### Gate Configuration (Production Defaults)

```python
WalkForwardGateConfig(
    enabled=True,
    min_oos_sharpe=0.0,          # All folds must have positive OOS Sharpe
    max_is_oos_sharpe_ratio=1.5,  # IS/OOS ratio ≤ 1.5 (overfitting ceiling)
    require_all_folds_positive_sharpe=True,
    min_folds_required=5,
)
```

---

## Pass/Fail Criteria

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Per-fold OOS Sharpe | > 0.0 for all folds | Any fold with negative OOS Sharpe indicates the strategy fails out-of-sample in that period |
| IS/OOS Sharpe ratio (per fold) | ≤ 1.5 | Ratios > 1.5 indicate the in-sample fit is ≥ 50% better than OOS — strong overfitting signal |
| Aggregate IS/OOS Sharpe ratio | ≤ 1.5 | Same ceiling applied to the aggregate OOS Sharpe vs IS Sharpe |
| Minimum number of folds | 5 | The standard walk-forward uses 5 folds; fewer indicates insufficient data |
| All folds must have positive OOS Sharpe | True | Non-negotiable for production deployment |

### Failure Example

```
FAIL: Walk-forward CI gate failed with 2 issues:
  - Fold 3: OOS Sharpe -0.1500 ≤ min 0.0000
  - Aggregate IS/OOS Sharpe ratio 2.10 > max 1.50
```

---

## CI Integration Strategy

### Phase 8 Implementation Plan

1. **Register pytest marker** in `pyproject.toml` under `[tool.pytest.ini_options.markers]`
2. **Create CI test file** `tests/ci/test_walk_forward_gate.py` with `@pytest.mark.walk_forward` decorator
3. **Create GitHub Actions workflow** `.github/workflows/walk-forward-gate.yml`:
   ```yaml
   name: Walk-Forward CI Gate
   on:
     pull_request:
       branches: [main]
   jobs:
     walk-forward:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: "3.12"
         - run: pip install uv && uv sync
         - run: uv run pytest -m walk_forward -v
   ```
4. **Add required status check** in GitHub branch protection rules for `main`
5. **Document run frequency**: on every PR to `main`; full walk-forward takes ~5-10 minutes on 12-year SET data

### Performance Budget

| Parameter | Estimate |
|-----------|----------|
| Data loading | < 30 seconds |
| Per-fold backtest (×5) | < 60 seconds each |
| Gate validation | < 1 second |
| Total | < 6 minutes |

### Cache Strategy

Feature panels and ParquetStore data should be cached between CI runs. The CI workflow should:

- Cache `data/` directory (ParquetStore) via `actions/cache@v4` with a hash of the data version
- Pre-compute feature panels and cache them to avoid re-computation on every run
- Use a separate cache key for the walk-forward gate to allow independent cache invalidation

---

## Integration with WalkForwardGate

The CI test function bridges `WalkForwardAnalyzer` (which produces `WalkForwardResult`) and `WalkForwardGate` (which accepts `dict[str, Any]` fold metrics):

```python
import pytest
from csm.portfolio.walkforward_gate import WalkForwardGate, WalkForwardGateConfig
from csm.research.walk_forward import WalkForwardAnalyzer, WalkForwardConfig

@pytest.mark.walk_forward
def test_walk_forward_ci_gate(data_fixture):
    analyzer = WalkForwardAnalyzer(store=data_fixture.store)
    wf_result = analyzer.run(
        feature_panel=data_fixture.feature_panel,
        prices=data_fixture.prices,
        config=data_fixture.backtest_config,
        wf_config=WalkForwardConfig(n_folds=5, test_years=1, min_train_years=5),
    )

    # Extract fold metrics as plain dicts for the gate
    fold_metrics = [
        {
            "fold": f.fold,
            "oos_sharpe": f.oos_metrics.get("sharpe", 0.0),
            "oos_cagr": f.oos_metrics.get("cagr"),
            "oos_max_dd": f.oos_metrics.get("max_drawdown"),
            "train_start": f.train_start,
            "train_end": f.train_end,
            "test_start": f.test_start,
            "test_end": f.test_end,
        }
        for f in wf_result.folds
    ]

    gate = WalkForwardGate()
    result = gate.validate(
        fold_metrics=fold_metrics,
        aggregate_oos_metrics=wf_result.aggregate_oos_metrics,
        is_metrics=wf_result.is_metrics,
        config=WalkForwardGateConfig(),
    )

    assert result.passed, f"Walk-forward CI gate failed:\n" + "\n".join(
        f"  - {f}" for f in result.failures
    )
```

---

## Alerting (Phase 8+)

When the walk-forward gate fails on a PR:

1. **PR comment**: The CI bot posts a comment with the failure details (which folds failed, by how much)
2. **Slack notification**: (optional) notify `#quant-alerts` channel
3. **PR block**: The PR cannot be merged until the gate passes or an override is approved

### Override Process

In exceptional circumstances (e.g., known regime change, data error), a lead quant researcher may override the gate failure. The override must:

1. Be documented in the PR description with justification
2. Include a link to the relevant incident/analysis
3. Be approved by a second reviewer with quant permissions

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Spec
