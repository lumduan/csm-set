"""Unit tests for Phase 5.8 — Structured logging."""

from __future__ import annotations

import json
import logging

import pytest
from api.logging import JsonFormatter, configure_logging, get_request_id

from csm.config.settings import Settings


class TestJsonFormatter:
    def test_formats_record_as_valid_json(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_includes_standard_fields(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="api.routers.signals",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Something happened",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "ts" in parsed
        assert parsed["level"] == "WARNING"
        assert parsed["logger"] == "api.routers.signals"
        assert parsed["msg"] == "Something happened"
        assert "request_id" in parsed

    def test_includes_exception_field_when_exc_info(self) -> None:
        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="Failed",
                args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exc" in parsed
        assert "test error" in parsed["exc"]

    def test_merges_extra_fields(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Event",
            args=(),
            exc_info=None,
        )
        record.__dict__["duration_ms"] = 42.5
        record.__dict__["method"] = "GET"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["duration_ms"] == 42.5
        assert parsed["method"] == "GET"

    def test_request_id_from_contextvar(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Event",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["request_id"] == get_request_id()

    def test_request_id_not_overridden_by_extra(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Event",
            args=(),
            exc_info=None,
        )
        record.__dict__["request_id"] = "fake-override"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["request_id"] == get_request_id()
        assert parsed["request_id"] != "fake-override"


class TestConfigureLogging:
    def test_sets_root_level_from_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CSM_LOG_LEVEL", "DEBUG")
        settings = Settings()
        configure_logging(settings)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        # Reset for subsequent tests
        root.setLevel(logging.INFO)

    def test_handlers_use_json_formatter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CSM_LOG_LEVEL", "INFO")
        settings = Settings()
        configure_logging(settings)
        root = logging.getLogger()
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(json_handlers) >= 1

    def test_uvicorn_access_silenced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CSM_LOG_LEVEL", "INFO")
        settings = Settings()
        configure_logging(settings)
        uvicorn_access = logging.getLogger("uvicorn.access")
        assert uvicorn_access.propagate is False
        assert len(uvicorn_access.handlers) == 0
