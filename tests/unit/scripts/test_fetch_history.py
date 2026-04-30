"""Unit tests for scripts/fetch_history.py."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from csm.config.constants import INDEX_SYMBOL
from csm.data.exceptions import StoreError

# Load scripts/fetch_history directly from its file path so tests are
# independent of sys.path and scripts package discovery.
_FH_FILE = Path(__file__).resolve().parents[3] / "scripts" / "fetch_history.py"
_fh_spec = importlib.util.spec_from_file_location("scripts.fetch_history", _FH_FILE)
assert _fh_spec is not None and _fh_spec.loader is not None
_fh_module = importlib.util.module_from_spec(_fh_spec)
sys.modules.setdefault("scripts.fetch_history", _fh_module)
_fh_spec.loader.exec_module(_fh_module)

_parse_args = _fh_module._parse_args
_migrate_legacy_raw = _fh_module._migrate_legacy_raw
main = _fh_module.main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_ADJUSTMENT = "dividends"


def _make_settings(
    *, public_mode: bool = False, adjustment: str = _DEFAULT_ADJUSTMENT
) -> MagicMock:
    settings = MagicMock()
    settings.public_mode = public_mode
    settings.log_level = "WARNING"
    settings.data_dir = "/tmp/csm_test_data"
    settings.tvkit_concurrency = 5
    settings.tvkit_retry_attempts = 3
    settings.tvkit_adjustment = adjustment
    return settings


def _minimal_df() -> pd.DataFrame:
    idx = pd.DatetimeIndex(["2024-01-01"], tz="UTC", name="datetime")
    return pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [1000.0]},
        index=idx,
    )


def _write_symbols_json(path: Path, symbols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"symbols": symbols}), encoding="utf-8")


def _save_key(mock_call: Any) -> str:
    """Extract the 'key' arg from a ParquetStore.save mock call (positional or keyword)."""
    return str(mock_call.args[0] if mock_call.args else mock_call.kwargs["key"])


def _fetch_symbols_arg(mock_call: Any) -> list[str]:
    """Extract the 'symbols' arg from a fetch_batch mock call (positional or keyword)."""
    return list(mock_call.args[0] if mock_call.args else mock_call.kwargs["symbols"])


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_already_stored_symbols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Symbols already in store are excluded from fetch_batch call."""
    symbols = ["SET:AOT", "SET:PTT", "SET:KBANK"]
    _write_symbols_json(tmp_path / "universe" / "symbols.json", symbols)

    mock_store = MagicMock()
    mock_store.exists.side_effect = lambda s: s in {"SET:AOT", "SET:PTT", INDEX_SYMBOL}
    mock_store.save = MagicMock()

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock(return_value={"SET:KBANK": _minimal_df()})

    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--data-dir", str(tmp_path)])

    with (
        patch("scripts.fetch_history.Settings", return_value=_make_settings()),
        patch("scripts.fetch_history.ParquetStore", return_value=mock_store),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        await main()

    mock_loader.fetch_batch.assert_called_once()
    assert _fetch_symbols_arg(mock_loader.fetch_batch.call_args) == ["SET:KBANK"]


@pytest.mark.asyncio
async def test_all_symbols_already_stored_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When all symbols are cached, fetch_batch is not called and no failures file is created."""
    symbols = ["SET:AOT", "SET:PTT"]
    _write_symbols_json(tmp_path / "universe" / "symbols.json", symbols)

    mock_store = MagicMock()
    mock_store.exists.return_value = True

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock()

    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--data-dir", str(tmp_path)])

    with (
        patch("scripts.fetch_history.Settings", return_value=_make_settings()),
        patch("scripts.fetch_history.ParquetStore", return_value=mock_store),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        await main()

    mock_loader.fetch_batch.assert_not_called()
    assert not (tmp_path / "raw" / _DEFAULT_ADJUSTMENT / "fetch_failures.json").exists()


# ---------------------------------------------------------------------------
# Save behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saves_fetched_symbols_to_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each successfully fetched symbol is saved with its raw symbol string as key."""
    symbols = ["SET:AOT", "SET:PTT"]
    _write_symbols_json(tmp_path / "universe" / "symbols.json", symbols)

    mock_store = MagicMock()
    mock_store.exists.side_effect = lambda s: s == INDEX_SYMBOL
    mock_store.save = MagicMock()

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock(return_value={s: _minimal_df() for s in symbols})

    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--data-dir", str(tmp_path)])

    with (
        patch("scripts.fetch_history.Settings", return_value=_make_settings()),
        patch("scripts.fetch_history.ParquetStore", return_value=mock_store),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        await main()

    saved_keys = [_save_key(c) for c in mock_store.save.call_args_list]
    assert sorted(saved_keys) == sorted(symbols)


@pytest.mark.asyncio
async def test_store_save_error_counted_as_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """StoreError on save() counts the symbol as failed and writes fetch_failures.json."""
    symbols = ["SET:AOT", "SET:PTT"]
    _write_symbols_json(tmp_path / "universe" / "symbols.json", symbols)

    mock_store = MagicMock()
    mock_store.exists.return_value = False

    def _save_side_effect(key: str, df: pd.DataFrame) -> None:
        if key == "SET:PTT":
            raise StoreError("disk full")

    mock_store.save.side_effect = _save_side_effect

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock(
        return_value={"SET:AOT": _minimal_df(), "SET:PTT": _minimal_df()}
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["fetch_history.py", "--data-dir", str(tmp_path), "--failure-threshold", "1.0"],
    )

    with (
        patch("scripts.fetch_history.Settings", return_value=_make_settings()),
        patch("scripts.fetch_history.ParquetStore", return_value=mock_store),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        await main()

    failures_path = tmp_path / "raw" / _DEFAULT_ADJUSTMENT / "fetch_failures.json"
    assert failures_path.exists()
    data = json.loads(failures_path.read_text())
    assert "SET:PTT" in data["failed_symbols"]


# ---------------------------------------------------------------------------
# Failure file lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writes_fetch_failures_json_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed symbol is recorded in fetch_failures.json with correct schema."""
    symbols = ["SET:AOT", "SET:PTT"]
    _write_symbols_json(tmp_path / "universe" / "symbols.json", symbols)

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.save = MagicMock()

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock(return_value={"SET:AOT": _minimal_df()})

    monkeypatch.setattr(
        sys,
        "argv",
        ["fetch_history.py", "--data-dir", str(tmp_path), "--failure-threshold", "1.0"],
    )

    with (
        patch("scripts.fetch_history.Settings", return_value=_make_settings()),
        patch("scripts.fetch_history.ParquetStore", return_value=mock_store),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        await main()

    failures_path = tmp_path / "raw" / _DEFAULT_ADJUSTMENT / "fetch_failures.json"
    assert failures_path.exists()
    data = json.loads(failures_path.read_text())
    assert set(data["failed_symbols"]) == {INDEX_SYMBOL, "SET:PTT"}
    assert data["count"] == 2
    assert "run_timestamp" in data
    assert data["adjustment"] == _DEFAULT_ADJUSTMENT


@pytest.mark.asyncio
async def test_deletes_fetch_failures_json_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale fetch_failures.json from a prior run is deleted on zero-failure success."""
    symbols = ["SET:AOT"]
    _write_symbols_json(tmp_path / "universe" / "symbols.json", symbols)

    raw_dir = tmp_path / "raw" / _DEFAULT_ADJUSTMENT
    raw_dir.mkdir(parents=True, exist_ok=True)
    stale = raw_dir / "fetch_failures.json"
    stale.write_text(
        json.dumps(
            {
                "run_timestamp": "old",
                "adjustment": _DEFAULT_ADJUSTMENT,
                "failed_symbols": ["SET:AOT"],
                "count": 1,
            }
        )
    )

    mock_store = MagicMock()
    mock_store.exists.side_effect = lambda s: s == INDEX_SYMBOL
    mock_store.save = MagicMock()

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock(return_value={"SET:AOT": _minimal_df()})

    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--data-dir", str(tmp_path)])

    with (
        patch("scripts.fetch_history.Settings", return_value=_make_settings()),
        patch("scripts.fetch_history.ParquetStore", return_value=mock_store),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        await main()

    assert not stale.exists()


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exits_nonzero_on_high_failure_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sys.exit(1) when failure rate exceeds the configured threshold."""
    symbols = ["SET:AOT", "SET:PTT", "SET:KBANK"]
    _write_symbols_json(tmp_path / "universe" / "symbols.json", symbols)

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.save = MagicMock()

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock(return_value={})  # all fail

    monkeypatch.setattr(
        sys,
        "argv",
        ["fetch_history.py", "--data-dir", str(tmp_path), "--failure-threshold", "0.5"],
    )

    with (
        patch("scripts.fetch_history.Settings", return_value=_make_settings()),
        patch("scripts.fetch_history.ParquetStore", return_value=mock_store),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        with pytest.raises(SystemExit) as exc_info:
            await main()

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_public_mode_exits_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sys.exit(1) when public_mode=True; fetch_batch is never called."""
    _write_symbols_json(tmp_path / "universe" / "symbols.json", ["SET:AOT"])

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock()

    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--data-dir", str(tmp_path)])

    with (
        patch("scripts.fetch_history.Settings", return_value=_make_settings(public_mode=True)),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        with pytest.raises(SystemExit) as exc_info:
            await main()

    assert exc_info.value.code == 1
    mock_loader.fetch_batch.assert_not_called()


@pytest.mark.asyncio
async def test_exits_if_symbols_json_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sys.exit(1) when symbols.json does not exist."""
    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--data-dir", str(tmp_path)])

    with patch("scripts.fetch_history.Settings", return_value=_make_settings()):
        with pytest.raises(SystemExit) as exc_info:
            await main()

    assert exc_info.value.code == 1


@pytest.mark.parametrize(
    "content",
    [
        "not valid json{{",
        '{"symbols": "SET:AOT"}',  # string instead of list
        '{"symbols": [123, "SET:PTT"]}',  # non-str element in list
        '{"no_symbols_key": []}',  # missing "symbols" key
        '{"symbols": []}',  # empty list
    ],
)
@pytest.mark.asyncio
async def test_exits_if_symbols_json_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """sys.exit(1) for malformed or structurally invalid symbols.json."""
    universe_dir = tmp_path / "universe"
    universe_dir.mkdir(parents=True, exist_ok=True)
    (universe_dir / "symbols.json").write_text(content, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--data-dir", str(tmp_path)])

    with patch("scripts.fetch_history.Settings", return_value=_make_settings()):
        with pytest.raises(SystemExit) as exc_info:
            await main()

    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# CLI validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv_extra",
    [
        ["--bars", "0"],
        ["--bars", "-1"],
        ["--failure-threshold", "-0.1"],
        ["--failure-threshold", "2.0"],
    ],
)
def test_invalid_cli_args_exit_code_2(
    monkeypatch: pytest.MonkeyPatch, argv_extra: list[str]
) -> None:
    """argparse rejects invalid --bars and --failure-threshold values with exit code 2."""
    monkeypatch.setattr(sys, "argv", ["fetch_history.py", *argv_extra])

    with pytest.raises(SystemExit) as exc_info:
        _parse_args()

    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Phase 1.8 — Adjustment flag and storage layout
# ---------------------------------------------------------------------------


def test_default_adjustment_arg_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """--adjustment defaults to None (falls back to settings.tvkit_adjustment at runtime)."""
    monkeypatch.setattr(sys, "argv", ["fetch_history.py"])
    args = _parse_args()
    assert args.adjustment is None


def test_adjustment_dividends_arg_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """--adjustment dividends is parsed correctly."""
    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--adjustment", "dividends"])
    args = _parse_args()
    assert args.adjustment == "dividends"


def test_adjustment_splits_arg_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """--adjustment splits is parsed correctly."""
    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--adjustment", "splits"])
    args = _parse_args()
    assert args.adjustment == "splits"


def test_invalid_adjustment_arg_exits_code_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown --adjustment value exits with code 2 (argparse choices validation)."""
    monkeypatch.setattr(sys, "argv", ["fetch_history.py", "--adjustment", "raw"])
    with pytest.raises(SystemExit) as exc_info:
        _parse_args()
    assert exc_info.value.code == 2


@pytest.mark.asyncio
async def test_adjustment_dividends_stores_in_dividends_subdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--adjustment dividends routes the store to data/raw/dividends/."""
    symbols = ["SET:AOT"]
    _write_symbols_json(tmp_path / "universe" / "symbols.json", symbols)

    captured_paths: list[Path] = []

    class _CapturingParquetStore:
        def __init__(self, base_dir: Path) -> None:
            captured_paths.append(base_dir)

        def exists(self, key: str) -> bool:
            return key == INDEX_SYMBOL

        def save(self, key: str, df: Any) -> None:
            pass

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock(return_value={"SET:AOT": _minimal_df()})

    monkeypatch.setattr(
        sys, "argv", ["fetch_history.py", "--data-dir", str(tmp_path), "--adjustment", "dividends"]
    )

    with (
        patch(
            "scripts.fetch_history.Settings", return_value=_make_settings(adjustment="dividends")
        ),
        patch("scripts.fetch_history.ParquetStore", side_effect=_CapturingParquetStore),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        await main()

    assert any(p == tmp_path / "raw" / "dividends" for p in captured_paths)


@pytest.mark.asyncio
async def test_adjustment_splits_stores_in_splits_subdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--adjustment splits routes the store to data/raw/splits/."""
    symbols = ["SET:AOT"]
    _write_symbols_json(tmp_path / "universe" / "symbols.json", symbols)

    captured_paths: list[Path] = []

    class _CapturingParquetStore:
        def __init__(self, base_dir: Path) -> None:
            captured_paths.append(base_dir)

        def exists(self, key: str) -> bool:
            return key == INDEX_SYMBOL

        def save(self, key: str, df: Any) -> None:
            pass

    mock_loader = MagicMock()
    mock_loader.fetch_batch = AsyncMock(return_value={"SET:AOT": _minimal_df()})

    monkeypatch.setattr(
        sys, "argv", ["fetch_history.py", "--data-dir", str(tmp_path), "--adjustment", "splits"]
    )

    with (
        patch("scripts.fetch_history.Settings", return_value=_make_settings(adjustment="splits")),
        patch("scripts.fetch_history.ParquetStore", side_effect=_CapturingParquetStore),
        patch("scripts.fetch_history.OHLCVLoader", return_value=mock_loader),
    ):
        await main()

    assert any(p == tmp_path / "raw" / "splits" for p in captured_paths)


# ---------------------------------------------------------------------------
# Phase 1.8 — Legacy migration
# ---------------------------------------------------------------------------


def test_migrate_legacy_raw_moves_parquet_files(tmp_path: Path) -> None:
    """_migrate_legacy_raw moves *.parquet files from raw_root to raw_root/splits/."""
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    (raw_root / "SET%3AAOT.parquet").write_bytes(b"")
    (raw_root / "SET%3APTT.parquet").write_bytes(b"")

    _migrate_legacy_raw(raw_root)

    assert not (raw_root / "SET%3AAOT.parquet").exists()
    assert not (raw_root / "SET%3APTT.parquet").exists()
    assert (raw_root / "splits" / "SET%3AAOT.parquet").exists()
    assert (raw_root / "splits" / "SET%3APTT.parquet").exists()


def test_migrate_legacy_raw_is_idempotent(tmp_path: Path) -> None:
    """Running _migrate_legacy_raw twice does not move already-migrated files."""
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    (raw_root / "SET%3AAOT.parquet").write_bytes(b"")

    _migrate_legacy_raw(raw_root)
    _migrate_legacy_raw(raw_root)

    # The file should be in splits/ exactly once
    splits_dir = raw_root / "splits"
    assert (splits_dir / "SET%3AAOT.parquet").exists()
    assert not (raw_root / "SET%3AAOT.parquet").exists()


def test_migrate_legacy_raw_no_op_when_empty(tmp_path: Path) -> None:
    """_migrate_legacy_raw is a no-op when no flat *.parquet files exist."""
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    _migrate_legacy_raw(raw_root)

    assert not (raw_root / "splits").exists()


def test_migrate_legacy_raw_no_op_when_dir_missing(tmp_path: Path) -> None:
    """_migrate_legacy_raw is safe to call even if raw_root does not exist."""
    raw_root = tmp_path / "raw_nonexistent"
    # Should not raise
    _migrate_legacy_raw(raw_root)
