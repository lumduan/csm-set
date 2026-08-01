"""Integration tests for Phase 5.5 — Scheduler manual trigger endpoint.

Validates POST /api/v1/scheduler/run/{job_id} lifecycle, public-mode
gating, job-id validation, and marker file persistence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
from api.scheduler.jobs import DEFAULT_LIVE_PORTFOLIO_PATH, _held_symbols_from_config
from fastapi.testclient import TestClient

from csm.config.constants import INDEX_SYMBOL


def _echo_requested_symbols(symbols: list[str], *_args: object, **_kwargs: object) -> dict:
    """Return a frame for every requested symbol, so no retry/backoff loop is entered."""
    dates = pd.date_range("2024-01-01", periods=3, freq="D", tz="Asia/Bangkok")
    frame = pd.DataFrame(
        {
            "open": [100.0] * 3,
            "high": [101.0] * 3,
            "low": [99.0] * 3,
            "close": [100.5] * 3,
            "volume": [1_000_000.0] * 3,
        },
        index=dates,
    )
    return {s: frame for s in symbols}


class TestManualTrigger:
    """POST /api/v1/scheduler/run/{job_id} endpoint behaviour."""

    def test_trigger_daily_refresh_returns_accepted(self, private_client: TestClient) -> None:
        resp = private_client.post("/api/v1/scheduler/run/daily_refresh")
        assert resp.status_code == 200
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "accepted"

    def test_trigger_invalid_job_id_returns_400(self, private_client: TestClient) -> None:
        resp = private_client.post("/api/v1/scheduler/run/nonexistent_job")
        assert resp.status_code == 400
        body = resp.json()
        assert "detail" in body
        assert "nonexistent_job" in body["detail"]

    def test_trigger_blocked_in_public_mode(self, client: TestClient) -> None:
        resp = client.post("/api/v1/scheduler/run/daily_refresh")
        assert resp.status_code == 403
        assert "Disabled in public mode" in resp.json()["detail"]

    def test_trigger_poll_to_terminal(self, private_client: TestClient) -> None:
        # The loader is mocked so the job terminates deterministically. Without it this
        # test ran the REAL daily refresh, attempting live tvkit fetches with retries,
        # and could not reach a terminal state inside the 5 s poll budget on CI.
        terminal_states = {"succeeded", "failed", "cancelled"}
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as mock_build_loader,
            patch("api.scheduler.jobs.FeaturePipeline"),
            patch("api.scheduler.jobs._sleep", new=AsyncMock()),
        ):
            mock_build_loader.return_value.fetch_batch = AsyncMock(
                side_effect=_echo_requested_symbols
            )

            submit_resp = private_client.post("/api/v1/scheduler/run/daily_refresh")
            assert submit_resp.status_code == 200
            job_id: str = submit_resp.json()["job_id"]

            for _ in range(50):
                resp = private_client.get(f"/api/v1/jobs/{job_id}")
                assert resp.status_code == 200
                status: str = resp.json()["status"]
                if status in terminal_states:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError(f"Scheduler trigger job {job_id} did not reach terminal state")

        body = resp.json()
        assert body["job_id"] == job_id
        assert body["kind"] == "data_refresh"
        assert body["status"] in terminal_states
        assert body["started_at"] is not None
        assert body["finished_at"] is not None

    def test_trigger_writes_marker_file_on_success(
        self, private_client: TestClient, tmp_path: Path
    ) -> None:
        # Echo back whatever is requested. Returning only the universe symbols is not
        # enough: daily_refresh fetches the HELD symbols first, and those are read from
        # the real configs/live_portfolio.yaml — so any name missing from the mock sends
        # the job into its exponential-backoff retry loop and it never reaches terminal.
        with (
            patch("api.scheduler.jobs.build_ohlcv_loader") as mock_build_loader,
            patch("api.scheduler.jobs._sleep", new=AsyncMock()),
        ):
            mock_loader = mock_build_loader.return_value
            mock_loader.fetch_batch = AsyncMock(side_effect=_echo_requested_symbols)

            with patch("api.scheduler.jobs.FeaturePipeline"):
                submit_resp = private_client.post("/api/v1/scheduler/run/daily_refresh")
                assert submit_resp.status_code == 200
                job_id: str = submit_resp.json()["job_id"]

                for _ in range(50):
                    resp = private_client.get(f"/api/v1/jobs/{job_id}")
                    assert resp.status_code == 200
                    if resp.json()["status"] in {"succeeded", "failed"}:
                        break
                    time.sleep(0.1)

        body = resp.json()
        assert body["status"] == "succeeded"

        marker_path = tmp_path / "results" / ".tmp" / "last_refresh.json"
        assert marker_path.is_file()
        marker = json.loads(marker_path.read_text())
        # The marker counts the universe symbols, the SET index that daily_refresh
        # prepends (it gates residual_momentum / sharpe_momentum in the pipeline),
        # PLUS the held book, which is fetched first from the real
        # configs/live_portfolio.yaml. Derived rather than hardcoded so a rebalance
        # that changes the position count does not break this test.
        expected_fetched = len(
            {"SET001", "SET002", "SET003", INDEX_SYMBOL}
            | set(_held_symbols_from_config(DEFAULT_LIVE_PORTFOLIO_PATH))
        )
        assert marker["symbols_fetched"] == expected_fetched
        assert marker["failures"] == 0
        assert marker["index_fetched"] is True
        assert "timestamp" in marker
        assert "duration_seconds" in marker
