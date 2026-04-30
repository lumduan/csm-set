"""Shared fixtures for integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def public_client(client: TestClient) -> TestClient:
    """Alias for the Phase 5.1/5.2 client fixture (public mode)."""
    return client


@pytest.fixture
def tmp_results_signals_full(tmp_results: Path) -> Path:
    """Extend tmp_results with realistic signal ranking data."""
    signals_path = tmp_results / "signals" / "latest_ranking.json"
    data = {
        "as_of": "2026-04-21",
        "rankings": [
            {"symbol": "SET001", "mom_12_1": 0.15, "mom_12_1_rank": 0.95, "mom_12_1_quintile": 5},
            {"symbol": "SET002", "mom_12_1": 0.08, "mom_12_1_rank": 0.72, "mom_12_1_quintile": 4},
        ],
    }
    signals_path.write_text(json.dumps(data))
    return tmp_results


@pytest.fixture
def tmp_results_portfolio_full(tmp_results: Path) -> Path:
    """Extend tmp_results with realistic portfolio summary data."""
    summary_path = tmp_results / "backtest" / "summary.json"
    data = {
        "generated_at": "2026-04-21T00:00:00+07:00",
        "cagr": 0.15,
        "sharpe": 1.2,
        "sortino": 1.8,
        "max_drawdown": -0.25,
    }
    summary_path.write_text(json.dumps(data))
    return tmp_results


@pytest.fixture
def tmp_results_malformed(tmp_results: Path) -> Path:
    """Replace JSON files with malformed content for 500 error-path tests."""
    (tmp_results / "signals" / "latest_ranking.json").write_text("not valid json{{{")
    (tmp_results / "backtest" / "summary.json").write_text("{{{bad json")
    return tmp_results
