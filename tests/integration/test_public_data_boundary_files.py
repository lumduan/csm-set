"""Data boundary audit — file system layer.

Walks ``results/**/*.json`` and ``results/**/*.html`` (excluding ``.tmp/``)
and fails if any committed file contains forbidden OHLCV keys, large numeric
arrays that look like raw price series, or HTML tables with > 4 numeric columns
(standard OHLCV table has 5: O, H, L, C, V).
"""

from __future__ import annotations

import json
from collections.abc import Generator
from html.parser import HTMLParser
from pathlib import Path

import pytest

FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {"open", "high", "low", "close", "volume", "adj_close", "adjusted_close"}
)

LARGE_ARRAY_THRESHOLD: int = 400
NUMERIC_COLUMN_THRESHOLD: int = 4
RESULTS_ROOT: Path = Path("results")


# ---------------------------------------------------------------------------
# JSON scanners
# ---------------------------------------------------------------------------


def _scan_json_keys(obj: object, path: str = "$") -> Generator[tuple[str, str], None, None]:
    """Yield ``(json_path, forbidden_key)`` for any dict key matching a forbidden OHLCV name.

    Keys are matched case-insensitively.  The path uses JavaScript-style notation
    (``$.key``, ``$.arr[0].nested``) so failure messages are immediately actionable.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}"
            if key.lower() in FORBIDDEN_KEYS:
                yield child_path, key
            yield from _scan_json_keys(value, child_path)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            yield from _scan_json_keys(item, f"{path}[{idx}]")


def _scan_large_numeric_arrays(
    obj: object, path: str = "$"
) -> Generator[tuple[str, int], None, None]:
    """Yield ``(json_path, length)`` for any list of > 400 numbers — a heuristic for
    raw price series disguised under a benign key name."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}"
            # Check *before* recursing so we catch the array at its direct key.
            if (
                isinstance(value, list)
                and len(value) > LARGE_ARRAY_THRESHOLD
                and all(isinstance(v, (int, float)) for v in value)
            ):
                yield child_path, len(value)
            yield from _scan_large_numeric_arrays(value, child_path)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            yield from _scan_large_numeric_arrays(item, f"{path}[{idx}]")


# ---------------------------------------------------------------------------
# HTML scanners
# ---------------------------------------------------------------------------


class _TableColumnCounter(HTMLParser):
    """Extract ``<table>`` elements and count numeric-heavy columns.

    A "numeric column" is one where > 80 % of non-empty text content parses as
    a number.  Tables with > 5 such columns are flagged as potential raw-price
    dumps (rendered notebook charts typically have 0 numeric columns).
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_table: bool = False
        self._in_tr: bool = False
        self._current_row: list[str] = []
        self._rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self._rows = []
        elif tag == "tr" and self._in_table:
            self._in_tr = True
            self._current_row = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._in_table = False
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            if self._current_row:
                self._rows.append(self._current_row)
                self._current_row = []

    def handle_data(self, data: str) -> None:
        if self._in_tr:
            self._current_row.append(data.strip())

    def tables_with_numeric_columns(
        self, threshold: int = NUMERIC_COLUMN_THRESHOLD
    ) -> list[tuple[int, int]]:
        """Return ``(table_index, num_numeric_columns)`` for each suspicious table."""
        suspicious: list[tuple[int, int]] = []
        # The parser can visit multiple tables; we count the one we just collected.
        if not self._rows:
            return suspicious
        col_count = len(self._rows[0]) if self._rows else 0
        if col_count == 0:
            return suspicious
        # Skip the header row (index 0) so column labels like "Open" or
        # "Close" don't dilute the numeric ratio below the detection threshold.
        data_rows = self._rows[1:] if len(self._rows) > 1 else []
        if not data_rows:
            return suspicious
        numeric_cols = 0
        for col_idx in range(col_count):
            values = [row[col_idx] for row in data_rows if col_idx < len(row) and row[col_idx]]
            if not values:
                continue
            numeric_count = 0
            for v in values:
                try:
                    float(v.replace(",", "").replace("%", ""))
                    numeric_count += 1
                except ValueError:
                    pass
            if numeric_count / len(values) > 0.8:
                numeric_cols += 1
        if numeric_cols > threshold:
            suspicious.append((0, numeric_cols))
        return suspicious


def _scan_html_tables(filepath: Path) -> list[str]:
    """Return error messages for any ``<table>`` in *filepath* that looks like a price dump."""
    errors: list[str] = []
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return errors
    parser = _TableColumnCounter()
    parser.feed(text)
    for table_idx, num_cols in parser.tables_with_numeric_columns():
        errors.append(
            f"{filepath}: <table> #{table_idx} has {num_cols} numeric columns "
            f"(>{NUMERIC_COLUMN_THRESHOLD}) — possible raw price data"
        )
    return errors


# ---------------------------------------------------------------------------
# File collectors
# ---------------------------------------------------------------------------


def _collect_json_files(root: Path) -> list[Path]:
    """Return every ``.json`` file under *root*, excluding ``.tmp/``."""
    if not root.is_dir():
        return []
    files: list[Path] = []
    for p in root.rglob("*.json"):
        if ".tmp" in p.parts:
            continue
        if p.is_file():
            files.append(p)
    return sorted(files)


def _collect_html_files(root: Path) -> list[Path]:
    """Return every ``.html`` file under *root*, excluding ``.tmp/``."""
    if not root.is_dir():
        return []
    files: list[Path] = []
    for p in root.rglob("*.html"):
        if ".tmp" in p.parts:
            continue
        if p.is_file():
            files.append(p)
    return sorted(files)


# ---------------------------------------------------------------------------
# Tests — JSON forbidden keys
# ---------------------------------------------------------------------------


_json_files = _collect_json_files(RESULTS_ROOT)


@pytest.mark.parametrize("filepath", _json_files, ids=lambda p: str(p))
def test_json_files_no_ohlcv_keys(filepath: Path) -> None:
    """Every committed JSON file must be free of OHLCV field names."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        pytest.skip(f"Cannot read {filepath}: {exc}")

    if not content.strip():
        return  # empty file is fine

    try:
        payload: object = json.loads(content)
    except json.JSONDecodeError as exc:
        pytest.fail(f"{filepath}: invalid JSON — {exc}")

    violations = list(_scan_json_keys(payload))
    if violations:
        msgs = "\n".join(f"  {path}: forbidden key '{key}'" for path, key in violations)
        pytest.fail(f"{filepath}: {len(violations)} OHLCV key(s) found in public data:\n{msgs}")


@pytest.mark.parametrize("filepath", _json_files, ids=lambda p: str(p))
def test_json_files_no_large_numeric_arrays(filepath: Path) -> None:
    """No JSON file should contain a numeric array > 400 entries — price-series heuristic."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        pytest.skip(f"Cannot read {filepath}: {exc}")

    if not content.strip():
        return

    try:
        payload: object = json.loads(content)
    except json.JSONDecodeError:
        return  # already caught by test_json_files_no_ohlcv_keys

    violations = list(_scan_large_numeric_arrays(payload))
    if violations:
        msgs = "\n".join(
            f"  {path}: {length} numeric entries (threshold={LARGE_ARRAY_THRESHOLD})"
            for path, length in violations
        )
        pytest.fail(
            f"{filepath}: {len(violations)} large numeric array(s) — possible price data:\n{msgs}"
        )


# ---------------------------------------------------------------------------
# Tests — HTML tables
# ---------------------------------------------------------------------------


_html_files = _collect_html_files(RESULTS_ROOT)


@pytest.mark.parametrize("filepath", _html_files, ids=lambda p: str(p))
def test_html_files_no_price_tables(filepath: Path) -> None:
    """No committed HTML file should contain a ``<table>`` with > 5 numeric columns."""
    errors = _scan_html_tables(filepath)
    if errors:
        pytest.fail("\n".join(errors))


# ---------------------------------------------------------------------------
# Tests — deliberate-leak negative tests
# ---------------------------------------------------------------------------


def test_deliberate_json_leak_detected(tmp_path: Path) -> None:
    """A JSON file with a forbidden key must be caught."""
    leak_file = tmp_path / "leak.json"
    leak_file.write_text(json.dumps({"summary": "ok", "close": 1.23}))
    payload = json.loads(leak_file.read_text())
    violations = list(_scan_json_keys(payload))
    assert len(violations) == 1
    assert violations[0][1] == "close"


def test_deliberate_large_array_detected(tmp_path: Path) -> None:
    """A JSON file with a 500-element numeric array must be caught."""
    leak_file = tmp_path / "leak_array.json"
    leak_file.write_text(json.dumps({"prices": list(range(500))}))
    payload = json.loads(leak_file.read_text())
    violations = list(_scan_large_numeric_arrays(payload))
    assert len(violations) == 1
    assert violations[0][1] == 500


def test_deliberate_html_table_detected(tmp_path: Path) -> None:
    """An HTML file with a raw price table must be caught."""
    html = """<html><body><table>
<tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr>
<tr><td>2024-01-01</td><td>100</td><td>105</td><td>99</td><td>103</td><td>1000000</td></tr>
<tr><td>2024-01-02</td><td>103</td><td>107</td><td>101</td><td>105</td><td>1200000</td></tr>
</table></body></html>"""
    html_file = tmp_path / "leak.html"
    html_file.write_text(html)
    errors = _scan_html_tables(html_file)
    assert len(errors) == 1
    assert "numeric columns" in errors[0]
