"""Integration tests for scripts/export_results.py.

Covers idempotency, schema-data co-validation, notebook HTML sanitization,
resource logging, CLI flags, and the public-mode guard.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from csm.research.backtest import BacktestConfig

# Load scripts._export_models via importlib to avoid namespace conflicts with
# the tests.unit.scripts package during pytest collection.
_EX_MODELS_FILE = Path(__file__).resolve().parents[2] / "scripts" / "_export_models.py"
_ex_models_spec = importlib.util.spec_from_file_location("scripts._export_models", _EX_MODELS_FILE)
assert _ex_models_spec is not None and _ex_models_spec.loader is not None
_ex_models_module = importlib.util.module_from_spec(_ex_models_spec)
sys.modules.setdefault("scripts._export_models", _ex_models_module)
_ex_models_spec.loader.exec_module(_ex_models_module)

ExportResultsConfig = _ex_models_module.ExportResultsConfig

# ── Load the script module ───────────────────────────────────────────

_EX_FILE = Path(__file__).resolve().parents[2] / "scripts" / "export_results.py"
_ex_spec = importlib.util.spec_from_file_location("scripts.export_results", _EX_FILE)
assert _ex_spec is not None and _ex_spec.loader is not None
_ex_module = importlib.util.module_from_spec(_ex_spec)
sys.modules.setdefault("scripts.export_results", _ex_module)
_ex_spec.loader.exec_module(_ex_module)

export_notebooks = _ex_module.export_notebooks
export_backtest = _ex_module.export_backtest
export_signals = _ex_module.export_signals
main = _ex_module.main
_parse_args = _ex_module._parse_args


# ── Helpers ───────────────────────────────────────────────────────────


def _has_jupyter() -> bool:
    return shutil.which("uv") is not None and shutil.which("jupyter") is not None or True


def _patch_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point settings to the same data dir used by private_store."""
    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    from csm.config.settings import Settings as _Settings

    _settings_mod = sys.modules["csm.config.settings"]
    _settings_mod.settings = _Settings()  # type: ignore[attr-defined]

    # Patch the script module's local binding
    _ex_module.settings = _settings_mod.settings  # type: ignore[attr-defined]


# ── Notebook HTML sanitization ────────────────────────────────────────


@pytest.fixture
def fixture_notebook(tmp_path: Path) -> Path:
    """Create a tiny .ipynb with an OHLCV code cell."""
    nb_dir = tmp_path / "fixture_nbs"
    nb_dir.mkdir(parents=True, exist_ok=True)
    nb_path = nb_dir / "test_secret.ipynb"

    nb_content: dict[str, object] = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
        },
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# OHLCV test cell — should NOT appear in HTML\n",
                    "secret_close = 123.45\n",
                    "oh = {'open': 100, 'high': 110}\n",
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Public Research Heading\n"],
            },
        ],
    }
    nb_path.write_text(json.dumps(nb_content), encoding="utf-8")
    return nb_path


@pytest.mark.asyncio
async def test_notebook_html_no_input(
    fixture_notebook: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Export fixture notebook; assert code cell content absent from HTML."""
    if not _has_jupyter():
        pytest.skip("jupyter nbconvert not available")

    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    config = ExportResultsConfig(
        notebook_dir=fixture_notebook.parent,
        output_dir=Path(str(tmp_path / "static_out")),
        timeout_s=120,
    )

    await export_notebooks(config)

    html_path = config.output_dir / "notebooks" / f"{fixture_notebook.stem}.html"
    assert html_path.exists(), f"HTML not found at {html_path}"

    html_content = html_path.read_text()
    assert "secret_close" not in html_content, "Code cell leaked into HTML"
    assert "Public Research Heading" in html_content, "Markdown cell missing from HTML"
    assert "OHLCV test cell" not in html_content, "Code cell source leaked into HTML"


@pytest.mark.asyncio
async def test_resource_logging(
    fixture_notebook: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """Assert peak-memory log line appears after notebook export."""
    if not _has_jupyter():
        pytest.skip("jupyter nbconvert not available")

    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    config = ExportResultsConfig(
        notebook_dir=fixture_notebook.parent,
        output_dir=Path(str(tmp_path / "static_out")),
        timeout_s=120,
    )

    with caplog.at_level(logging.INFO):
        await export_notebooks(config)

    log_messages = [r.message for r in caplog.records]
    peak_lines = [m for m in log_messages if "peak" in m.lower() and "MB" in m]
    assert peak_lines, f"Peak memory log line not found in: {log_messages}"


# ── Backtest idempotency and schema match ─────────────────────────────


@pytest.fixture
def bt_config() -> BacktestConfig:
    """Short-horizon backtest config for 60-day synthetic data."""
    return BacktestConfig(formation_months=1, skip_months=0)


@pytest.mark.asyncio
async def test_backtest_idempotent(
    private_store: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bt_config: BacktestConfig,
) -> None:
    """Run export_backtest twice; assert byte-identical JSON except generated_at."""
    _patch_settings(monkeypatch, tmp_path)

    config = ExportResultsConfig(output_dir=Path(str(tmp_path / "static_out")))

    # First run
    await export_backtest(config, backtest_config=bt_config)
    first_run: dict[str, bytes] = {}
    for p in sorted((config.output_dir / "backtest").rglob("*.json")):
        if "schema" not in p.name:
            first_run[p.name] = p.read_bytes()

    # Second run
    await export_backtest(config, backtest_config=bt_config)
    second_run: dict[str, bytes] = {}
    for p in sorted((config.output_dir / "backtest").rglob("*.json")):
        if "schema" not in p.name:
            second_run[p.name] = p.read_bytes()

    assert set(first_run.keys()) == set(second_run.keys())
    for name, content in first_run.items():
        if name == "summary.json":
            f_data = json.loads(content)
            s_data = json.loads(second_run[name])
            assert "generated_at" in s_data
            f_data.pop("generated_at")
            s_data.pop("generated_at")
            assert f_data == s_data, "summary.json differs beyond generated_at"
        else:
            assert content == second_run[name], f"{name} is not byte-identical"


@pytest.mark.asyncio
async def test_signals_idempotent(
    private_store: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run export_signals twice; assert byte-identical JSON."""
    _patch_settings(monkeypatch, tmp_path)

    config = ExportResultsConfig(output_dir=Path(str(tmp_path / "static_out")))

    await export_signals(config)
    first_content = (config.output_dir / "signals" / "latest_ranking.json").read_bytes()

    await export_signals(config)
    second_content = (config.output_dir / "signals" / "latest_ranking.json").read_bytes()

    assert first_content == second_content, "signals JSON is not byte-identical"


@pytest.fixture
def _populated_export(
    private_store: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bt_config: BacktestConfig,
) -> Path:
    """Run all exports to populate results/static/ for schema-match tests."""
    _patch_settings(monkeypatch, tmp_path)
    config = ExportResultsConfig(output_dir=Path(str(tmp_path / "static_out")))

    async def _run() -> Path:
        await export_backtest(config, backtest_config=bt_config)
        await export_signals(config)
        return config.output_dir

    import asyncio

    return asyncio.run(_run())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_schema_matches_data(
    private_store: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bt_config: BacktestConfig,
) -> None:
    """Load each JSON, validate against its sibling schema.json using jsonschema."""
    import jsonschema

    _patch_settings(monkeypatch, tmp_path)

    config = ExportResultsConfig(output_dir=Path(str(tmp_path / "static_out")))
    await export_backtest(config, backtest_config=bt_config)
    await export_signals(config)

    for json_path in sorted(config.output_dir.rglob("*.json")):
        if json_path.name.endswith(".schema.json"):
            continue
        schema_path = json_path.with_name(json_path.name.replace(".json", ".schema.json"))
        assert schema_path.exists(), f"Missing schema sidecar for {json_path}"

        data = json.loads(json_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)


@pytest.mark.asyncio
async def test_schema_files_exist(
    private_store: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bt_config: BacktestConfig,
) -> None:
    """Every JSON has a sibling .schema.json."""
    _patch_settings(monkeypatch, tmp_path)

    config = ExportResultsConfig(output_dir=Path(str(tmp_path / "static_out")))
    await export_backtest(config, backtest_config=bt_config)
    await export_signals(config)

    json_files = [
        p for p in config.output_dir.rglob("*.json") if not p.name.endswith(".schema.json")
    ]
    assert len(json_files) >= 4, f"Expected at least 4 JSON files, got {len(json_files)}"

    for json_path in json_files:
        schema_path = json_path.with_name(json_path.name.replace(".json", ".schema.json"))
        assert schema_path.exists(), f"No schema for {json_path.name}"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert "$schema" in schema
        assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"


# ── Pydantic model validation ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_backtest_output_validates_against_model(
    private_store: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bt_config: BacktestConfig,
) -> None:
    """Backtest output passes Pydantic model validation."""
    AnnualReturns = _ex_models_module.AnnualReturns
    BacktestSummary = _ex_models_module.BacktestSummary
    EquityCurve = _ex_models_module.EquityCurve

    _patch_settings(monkeypatch, tmp_path)

    config = ExportResultsConfig(output_dir=Path(str(tmp_path / "static_out")))
    await export_backtest(config, backtest_config=bt_config)

    summary = BacktestSummary.model_validate_json(
        (config.output_dir / "backtest" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary.schema_version == "1.0"
    assert summary.metrics.cagr is not None

    equity = EquityCurve.model_validate_json(
        (config.output_dir / "backtest" / "equity_curve.json").read_text(encoding="utf-8")
    )
    assert len(equity.series) > 0

    annual = AnnualReturns.model_validate_json(
        (config.output_dir / "backtest" / "annual_returns.json").read_text(encoding="utf-8")
    )
    assert len(annual.rows) > 0


@pytest.mark.asyncio
async def test_signals_output_validates_against_model(
    private_store: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signal output passes Pydantic model validation."""
    SignalRanking = _ex_models_module.SignalRanking

    _patch_settings(monkeypatch, tmp_path)

    config = ExportResultsConfig(output_dir=Path(str(tmp_path / "static_out")))
    await export_signals(config)

    ranking = SignalRanking.model_validate_json(
        (config.output_dir / "signals" / "latest_ranking.json").read_text(encoding="utf-8")
    )
    assert ranking.schema_version == "1.0"
    for entry in ranking.rankings:
        assert 1 <= entry.quintile <= 5
        assert 0.0 <= entry.rank_pct <= 1.0


# ── CLI flags ─────────────────────────────────────────────────────────


def test_parse_args_default_all() -> None:
    """Default: all exports enabled."""
    with patch.object(sys, "argv", ["export_results.py"]):
        args = _parse_args()
    assert not args.notebooks_only
    assert not args.backtest_only
    assert not args.signals_only
    assert not args.skip_notebooks


def test_parse_args_notebooks_only() -> None:
    with patch.object(sys, "argv", ["export_results.py", "--notebooks-only"]):
        args = _parse_args()
    assert args.notebooks_only
    assert not args.backtest_only
    assert not args.signals_only


def test_parse_args_backtest_only() -> None:
    with patch.object(sys, "argv", ["export_results.py", "--backtest-only"]):
        args = _parse_args()
    assert not args.notebooks_only
    assert args.backtest_only
    assert not args.signals_only


def test_parse_args_signals_only() -> None:
    with patch.object(sys, "argv", ["export_results.py", "--signals-only"]):
        args = _parse_args()
    assert not args.notebooks_only
    assert not args.backtest_only
    assert args.signals_only


def test_parse_args_skip_notebooks() -> None:
    with patch.object(sys, "argv", ["export_results.py", "--skip-notebooks"]):
        args = _parse_args()
    assert args.skip_notebooks
    assert not args.notebooks_only


def test_parse_args_custom_dirs() -> None:
    with patch.object(
        sys,
        "argv",
        [
            "export_results.py",
            "--notebook-dir",
            "my_nbs",
            "--output-dir",
            "out",
            "--timeout",
            "300",
        ],
    ):
        args = _parse_args()
    assert args.notebook_dir == "my_nbs"
    assert args.output_dir == "out"
    assert args.timeout == 300


def test_parse_args_mutex_error() -> None:
    """Mutually exclusive flags cause argparse error."""
    with (
        patch.object(sys, "argv", ["export_results.py", "--notebooks-only", "--backtest-only"]),
        pytest.raises(SystemExit),
    ):
        _parse_args()


# ── Public mode guard ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_public_mode_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert RuntimeError when settings.public_mode is True."""
    monkeypatch.setenv("CSM_PUBLIC_MODE", "true")
    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CSM_RESULTS_DIR", str(tmp_path / "results"))

    from csm.config.settings import Settings as _Settings

    _settings_mod = sys.modules["csm.config.settings"]
    _settings_mod.settings = _Settings()  # type: ignore[attr-defined]

    _ex_module.settings = _settings_mod.settings  # type: ignore[attr-defined]

    with (
        patch.object(sys, "argv", ["export_results.py"]),
        pytest.raises(RuntimeError, match="owner-only"),
    ):
        await main()


# ── Empty data handling ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_signals_no_universe(
    private_store: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signal export tolerates missing universe_latest — sectors default to UNKNOWN."""
    _patch_settings(monkeypatch, tmp_path)

    # Remove universe_latest from the store
    import os

    universe_path = tmp_path / "data" / "processed" / "universe_latest.parquet"
    if universe_path.exists():
        os.remove(universe_path)

    config = ExportResultsConfig(output_dir=Path(str(tmp_path / "static_out")))
    await export_signals(config)

    ranking_path = config.output_dir / "signals" / "latest_ranking.json"
    assert ranking_path.exists()
    data = json.loads(ranking_path.read_text(encoding="utf-8"))
    if data.get("rankings"):
        # All sectors should be UNKNOWN since we removed the universe
        for entry in data["rankings"]:
            assert entry["sector"] == "UNKNOWN"
