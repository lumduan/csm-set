"""Unit tests for Settings loading and public_mode behaviour."""

import pytest

from csm.config.settings import Settings, get_settings


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
    from pydantic import ValidationError

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
    from pydantic import ValidationError

    monkeypatch.setenv("CSM_TVKIT_ADJUSTMENT", "raw")
    with pytest.raises(ValidationError):
        Settings()
