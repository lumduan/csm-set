"""Unit tests for Settings loading and public_mode behaviour."""

import json

import pytest
from pydantic import ValidationError

from csm.config.settings import Settings, TradingViewCookies, get_settings


def test_settings_loads_defaults() -> None:
    """Settings() with no env overrides returns correct defaults."""
    s = Settings()
    assert s.public_mode is False
    assert s.tvkit_concurrency == 5
    assert s.tvkit_retry_attempts == 3
    assert s.log_level == "INFO"
    assert str(s.data_dir) == "data"
    assert str(s.results_dir) == "results"


def test_public_mode_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """public_mode is False when CSM_PUBLIC_MODE is not set."""
    monkeypatch.delenv("CSM_PUBLIC_MODE", raising=False)
    s = Settings()
    assert s.public_mode is False


def test_public_mode_true_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """public_mode is True when CSM_PUBLIC_MODE=true is in the environment."""
    monkeypatch.setenv("CSM_PUBLIC_MODE", "true")
    s = Settings()
    assert s.public_mode is True


def test_get_settings_returns_singleton() -> None:
    """get_settings() returns the same instance on repeated calls."""
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b


def test_settings_is_frozen() -> None:
    """Direct attribute assignment on Settings raises ValidationError (frozen model)."""
    s = Settings()
    with pytest.raises((ValidationError, TypeError)):
        s.public_mode = True  # type: ignore[misc]


def test_tvkit_adjustment_defaults_to_dividends(monkeypatch: pytest.MonkeyPatch) -> None:
    """tvkit_adjustment defaults to 'dividends' when CSM_TVKIT_ADJUSTMENT is not set."""
    monkeypatch.delenv("CSM_TVKIT_ADJUSTMENT", raising=False)
    s = Settings()
    assert s.tvkit_adjustment == "dividends"


def test_tvkit_adjustment_accepts_splits(monkeypatch: pytest.MonkeyPatch) -> None:
    """tvkit_adjustment accepts 'splits' from the environment."""
    monkeypatch.setenv("CSM_TVKIT_ADJUSTMENT", "splits")
    s = Settings()
    assert s.tvkit_adjustment == "splits"


def test_tvkit_adjustment_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """tvkit_adjustment raises ValidationError for values outside {'splits', 'dividends'}."""
    monkeypatch.setenv("CSM_TVKIT_ADJUSTMENT", "raw")
    with pytest.raises(ValidationError):
        Settings()


def test_tvkit_auth_token_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """tvkit_auth_token is None (anonymous mode) when the env var is unset/empty."""
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", "")
    s = Settings()
    assert s.tvkit_auth_token is None
    assert s.tvkit_cookies is None


def test_tvkit_cookies_parses_json_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JSON cookie blob in TVKIT_AUTH_TOKEN parses into TradingViewCookies."""
    payload = {
        "sessionid": "abc123",
        "sessionid_sign": "v3:signed",
        "device_t": "device-token",
        "tv_ecuid": "uuid-here",
    }
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", json.dumps(payload))
    s = Settings()
    cookies = s.tvkit_cookies
    assert isinstance(cookies, TradingViewCookies)
    assert cookies.sessionid == "abc123"
    assert cookies.sessionid_sign == "v3:signed"
    assert cookies.as_cookie_dict() == payload


def test_tvkit_cookies_accepts_minimal_sessionid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only ``sessionid`` is required; missing companions stay None and drop out of the dict."""
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", json.dumps({"sessionid": "only-id"}))
    s = Settings()
    cookies = s.tvkit_cookies
    assert cookies is not None
    assert cookies.as_cookie_dict() == {"sessionid": "only-id"}


def test_tvkit_cookies_preserves_extra_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown cookies in the JSON blob are forwarded verbatim (extras allowed)."""
    payload = {"sessionid": "x", "csrftoken": "csrf-value", "_ga": "tracker"}
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", json.dumps(payload))
    s = Settings()
    cookies = s.tvkit_cookies
    assert cookies is not None
    flat = cookies.as_cookie_dict()
    assert flat["csrftoken"] == "csrf-value"
    assert flat["_ga"] == "tracker"


def test_tvkit_auth_token_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed JSON in TVKIT_AUTH_TOKEN raises ValidationError at startup."""
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", "not-json-at-all")
    with pytest.raises(ValidationError):
        Settings()


def test_tvkit_auth_token_requires_sessionid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cookie blob without sessionid is rejected — tvkit cannot authenticate without it."""
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", json.dumps({"sessionid_sign": "v3:..."}))
    with pytest.raises(ValidationError):
        Settings()


def test_tvkit_auth_token_ignores_csm_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CSM_TVKIT_AUTH_TOKEN prefix is intentionally NOT honoured.

    The token is shared with external tooling that also reads the bare
    ``TVKIT_AUTH_TOKEN`` env var, so we keep a single canonical name.
    """
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", "")
    monkeypatch.setenv("CSM_TVKIT_AUTH_TOKEN", json.dumps({"sessionid": "via-prefix"}))
    s = Settings()
    assert s.tvkit_auth_token is None
    assert s.tvkit_cookies is None


def test_db_write_enabled_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """db_write_enabled is False when CSM_DB_WRITE_ENABLED is not set."""
    monkeypatch.delenv("CSM_DB_WRITE_ENABLED", raising=False)
    s = Settings()
    assert s.db_write_enabled is False


def test_db_dsn_fields_default_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """All DB DSN fields default to None when env vars are unset."""
    for key in ("CSM_DB_CSM_SET_DSN", "CSM_DB_GATEWAY_DSN", "CSM_MONGO_URI"):
        monkeypatch.delenv(key, raising=False)
    s = Settings()
    assert s.db_csm_set_dsn is None
    assert s.db_gateway_dsn is None
    assert s.mongo_uri is None


def test_db_write_enabled_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """db_write_enabled is True when CSM_DB_WRITE_ENABLED=true is in the environment."""
    monkeypatch.setenv("CSM_DB_WRITE_ENABLED", "true")
    s = Settings()
    assert s.db_write_enabled is True


def test_db_dsn_fields_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB DSN fields read correctly from environment variables."""
    monkeypatch.setenv("CSM_DB_CSM_SET_DSN", "postgresql://user:pass@host:5432/db_csm_set")
    monkeypatch.setenv("CSM_DB_GATEWAY_DSN", "postgresql://user:pass@host:5432/db_gateway")
    monkeypatch.setenv("CSM_MONGO_URI", "mongodb://host:27017/")
    s = Settings()
    assert s.db_csm_set_dsn == "postgresql://user:pass@host:5432/db_csm_set"
    assert s.db_gateway_dsn == "postgresql://user:pass@host:5432/db_gateway"
    assert s.mongo_uri == "mongodb://host:27017/"
