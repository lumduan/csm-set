"""Live TradingView integration test for TVKIT_AUTH_TOKEN cookie auth.

This test actually hits TradingView and is therefore opt-in:

    RUN_TVKIT_LIVE=1 uv run pytest tests/integration/test_tvkit_auth_live.py -s

It is skipped by default so the standard test suite stays hermetic and CI
does not consume the owner's TradingView quota.

Purpose: prove that ``TVKIT_AUTH_TOKEN`` (a JSON cookie blob) authenticates
the WebSocket session well enough to lift the 5,000-bar anonymous cap and
return more than 10,000 bars for a liquid SET symbol.
"""

from __future__ import annotations

import os

import pytest

from csm.config.settings import Settings, TradingViewCookies
from csm.data.loader import OHLCVLoader

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("RUN_TVKIT_LIVE") != "1",
        reason=(
            "Live TradingView test is opt-in. Set RUN_TVKIT_LIVE=1 (and ensure "
            "TVKIT_AUTH_TOKEN is exported with valid session cookies) to run it."
        ),
    ),
]

# NASDAQ:AAPL has daily history back to 1980 — well over 10,000 daily bars,
# which is the bar count needed to prove the anonymous 5,000-bar cap was
# lifted by authenticated access.
LIVE_SYMBOL = "NASDAQ:AAPL"
LIVE_INTERVAL = "1D"
REQUESTED_BARS = 15_000
EXPECTED_MIN_BARS = 10_001


async def test_authenticated_fetch_returns_more_than_ten_thousand_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With TVKIT_AUTH_TOKEN cookies set, fetch returns >10,000 daily bars.

    The autouse ``_isolate_tvkit_auth_token`` fixture in tests/conftest.py
    clears the env var for every test by default — we re-export the operator's
    real value here so this single live test can authenticate.
    """
    real_token = os.environ.get("_REAL_TVKIT_AUTH_TOKEN") or _read_env_file_token()
    assert real_token, (
        "Live test requires the real TVKIT_AUTH_TOKEN. Either export "
        "_REAL_TVKIT_AUTH_TOKEN before running, or ensure .env contains a "
        "TVKIT_AUTH_TOKEN line."
    )
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", real_token)

    settings = Settings()
    cookies = settings.tvkit_cookies
    assert isinstance(cookies, TradingViewCookies), "TVKIT_AUTH_TOKEN failed to parse"
    assert cookies.sessionid, "sessionid is required for tvkit auth"

    loader = OHLCVLoader(settings)
    frame = await loader.fetch(symbol=LIVE_SYMBOL, interval=LIVE_INTERVAL, bars=REQUESTED_BARS)

    bar_count = len(frame)
    print(f"\nLIVE: fetched {bar_count} bars for {LIVE_SYMBOL} @ {LIVE_INTERVAL}")
    assert bar_count > EXPECTED_MIN_BARS, (
        f"Expected >{EXPECTED_MIN_BARS} bars with authenticated cookies; got {bar_count}. "
        "Either the cookies are stale (re-export them from your browser) or auth "
        "did not actually take effect — check tvkit logs for the auth-mode line."
    )
    assert frame.index.is_monotonic_increasing
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]


def _read_env_file_token() -> str | None:
    """Best-effort fallback: read TVKIT_AUTH_TOKEN from the project's .env file."""
    from pathlib import Path

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("TVKIT_AUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None
