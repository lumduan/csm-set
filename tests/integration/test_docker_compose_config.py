"""Structural validation tests for Phase 6.2 docker-compose configs.

These tests parse the YAML files and assert on their structure.
They do NOT require Docker to be installed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_COMPOSE = REPO_ROOT / "docker-compose.yml"
PRIVATE_COMPOSE = REPO_ROOT / "docker-compose.private.yml"


def _load_yaml(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def _service(doc: dict) -> dict:
    return doc["services"]["csm"]


# ---------------------------------------------------------------------------
# Public compose (docker-compose.yml)
# ---------------------------------------------------------------------------


class TestPublicCompose:
    def test_parses(self) -> None:
        """YAML parses without error."""
        doc = _load_yaml(PUBLIC_COMPOSE)
        assert "services" in doc
        assert "csm" in doc["services"]

    def test_single_port_8100(self) -> None:
        """Only port 8100 is exposed — port 8080 must not appear."""
        ports = _service(_load_yaml(PUBLIC_COMPOSE))["ports"]
        assert ports == ["8100:8000"], f"Expected only 8100:8000, got {ports}"

    def test_has_mem_limit(self) -> None:
        """mem_limit: 2g is set."""
        assert _service(_load_yaml(PUBLIC_COMPOSE))["mem_limit"] == "2g"

    def test_results_volume_readonly(self) -> None:
        """Results volume is read-only (suffixed with :ro)."""
        volumes = _service(_load_yaml(PUBLIC_COMPOSE))["volumes"]
        results_vol = [v for v in volumes if "results" in v]
        assert len(results_vol) == 1
        assert results_vol[0].endswith(":ro"), f"{results_vol[0]} is not read-only"

    def test_has_healthcheck(self) -> None:
        """Healthcheck stanza is present with expected keys."""
        hc = _service(_load_yaml(PUBLIC_COMPOSE))["healthcheck"]
        assert hc["interval"] == "30s"
        assert hc["timeout"] == "5s"
        assert hc["retries"] == 3
        assert hc["start_period"] == "20s"
        assert "curl" in hc["test"][1]

    def test_environment_public_mode_true(self) -> None:
        """CSM_PUBLIC_MODE is true in public compose."""
        env = _service(_load_yaml(PUBLIC_COMPOSE))["environment"]
        assert env["CSM_PUBLIC_MODE"] == "true"

    def test_environment_cors_wildcard(self) -> None:
        """CORS origins are wildcard in public compose."""
        env = _service(_load_yaml(PUBLIC_COMPOSE))["environment"]
        assert env["CSM_CORS_ALLOW_ORIGINS"] == "*"


# ---------------------------------------------------------------------------
# Private compose (docker-compose.private.yml)
# ---------------------------------------------------------------------------


class TestPrivateCompose:
    def test_parses(self) -> None:
        """YAML parses without error."""
        doc = _load_yaml(PRIVATE_COMPOSE)
        assert "services" in doc
        assert "csm" in doc["services"]

    def test_overrides_public_mode(self) -> None:
        """CSM_PUBLIC_MODE is set to false."""
        env = _service(_load_yaml(PRIVATE_COMPOSE))["environment"]
        assert env["CSM_PUBLIC_MODE"] == "false"

    def test_restricts_cors(self) -> None:
        """CORS origins are restricted to localhost dev origins."""
        env = _service(_load_yaml(PRIVATE_COMPOSE))["environment"]
        origins = env["CSM_CORS_ALLOW_ORIGINS"]
        assert "localhost:3000" in origins
        assert "localhost:5173" in origins

    def test_forwards_tvkit_auth_token(self) -> None:
        """TVKIT_AUTH_TOKEN is forwarded from the host shell with a required marker."""
        env = _service(_load_yaml(PRIVATE_COMPOSE))["environment"]
        token_value = env["TVKIT_AUTH_TOKEN"]
        # Compose ${VAR:?msg} interpolation form — fails fast when the host
        # has not exported a cookie blob, instead of booting unauthenticated.
        assert token_value.startswith("${TVKIT_AUTH_TOKEN")
        assert ":?" in token_value, "must use the required-variable marker"

    def test_results_volume_writable(self) -> None:
        """Results volume is writable — no :ro suffix."""
        volumes = _service(_load_yaml(PRIVATE_COMPOSE))["volumes"]
        results_vol = [v for v in volumes if "results" in v]
        assert len(results_vol) == 1
        assert not results_vol[0].endswith(":ro"), f"{results_vol[0]} should be writable"

    def test_data_volume_mounted(self) -> None:
        """Data directory is mounted for OHLCV access."""
        volumes = _service(_load_yaml(PRIVATE_COMPOSE))["volumes"]
        data_vol = [v for v in volumes if v.startswith("./data")]
        assert len(data_vol) == 1

    def test_no_browser_profile_mount(self) -> None:
        """Browser profile mounts are no longer needed under cookie-based auth."""
        volumes = _service(_load_yaml(PRIVATE_COMPOSE))["volumes"]
        browser_vols = [v for v in volumes if "google-chrome" in v or "firefox" in v]
        assert browser_vols == [], (
            "tvkit auth now uses TVKIT_AUTH_TOKEN cookies; remove browser-profile mounts"
        )

    def test_has_healthcheck(self) -> None:
        """Healthcheck stanza mirrors the public compose."""
        hc = _service(_load_yaml(PRIVATE_COMPOSE))["healthcheck"]
        assert hc["interval"] == "30s"
        assert hc["retries"] == 3

    def test_has_mem_limit(self) -> None:
        """mem_limit: 2g is set."""
        assert _service(_load_yaml(PRIVATE_COMPOSE))["mem_limit"] == "2g"
