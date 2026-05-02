# Development Guide

This page covers the development workflow, quality gate, commit conventions, code style, test layout, and local dev tips for csm-set contributors.

## Table of Contents

- [Workflow](#workflow)
- [Quality gate](#quality-gate)
- [Commit conventions](#commit-conventions)
- [Code style summary](#code-style-summary)
- [Test layout](#test-layout)
- [Testing security paths](#testing-security-paths)
- [Local dev tips](#local-dev-tips)

---

## Workflow

The standard development loop follows the process in `.claude/playbooks/feature-development.md`:

1. **Read** — study the related modules under `src/csm/` and their tests under `tests/`. Search existing helpers before writing new ones.
2. **Branch** — create a feature branch from `main`: `feature/<short-description>` or `fix/<short-description>`.
3. **Test first** — add a failing test in `tests/` that mirrors the source path. Test behaviour, not implementation.
4. **Implement** — write the smallest change that makes the test pass. Full type annotations. Pydantic at boundaries. ≤ 400 lines per file.
5. **Quality gate** — run the full gate locally (see below). All four commands must pass.
6. **Document** — docstring on every new public function (Google style). Update `docs/` if behaviour changes.
7. **Commit** — conventional commit message. One feature per commit.
8. **PR** — open a PR against `main` with a clear description. CI runs the same quality gate on push.

---

## Quality gate

Run before every commit. These are the exact same commands that `.github/workflows/ci.yml` runs on every push and PR:

```bash
uv run ruff check . \
  && uv run ruff format --check . \
  && uv run mypy src/ \
  && uv run pytest tests/ -v --cov=api --cov-fail-under=90
```

### What each command does

| Command | Purpose |
|---------|---------|
| `ruff check .` | Linting: catches unused imports, undefined names, style violations (E, F, I, UP, B, SIM rules) |
| `ruff format --check .` | Format check: verifies code is formatted with ruff (line length 100); use `ruff format .` to auto-fix |
| `mypy src/` | Static type checking: `strict` mode, all of `src/`; configuration in `[tool.mypy]` in `pyproject.toml` |
| `pytest tests/ -v --cov=api --cov-fail-under=90` | Test suite with coverage floor on `api/`; floor is configured in `pyproject.toml` so it applies locally and in CI |

The coverage floor (`--cov-fail-under=90`) is set in `[tool.pytest.ini_options].addopts` in `pyproject.toml`. This is the single source of truth — CI does not set a separate threshold. A developer running `uv run pytest` locally gets the same fail-fast behaviour as CI.

### Pre-commit hooks

If you have pre-commit installed, run:

```bash
uv run pre-commit install
```

This runs ruff and format checks automatically before each commit.

---

## Commit conventions

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scope): add sector-relative momentum feature
fix(scope): handle missing data in universe builder
docs(scope): expand public mode guide
test(scope): add IC analysis unit tests
ci(scope): add general lint/type/test workflow
refactor(scope): extract volume filtering into standalone module
```

Scopes align with the top-level module or concern: `data`, `features`, `portfolio`, `research`, `risk`, `api`, `ui`, `scripts`, `docker`, `docs`, `ci`, `config`.

Each commit should address one logical change. Separate cleanup/refactoring into its own commit.

---

## Code style summary

- **File size:** ≤ 400 lines per Python file. Split if exceeded.
- **Type annotations:** full annotations on all public functions. `mypy strict` mode is enabled project-wide.
- **Docstrings:** Google-style (`Args:`, `Returns:`, `Raises:`, `Example:`) on every public function. One-liner summary line.
- **Pydantic at boundaries:** function I/O crossing module boundaries goes through Pydantic models. No raw dicts passed between `src/csm/`, `api/`, and `ui/`.
- **Async I/O:** all HTTP uses `httpx.AsyncClient`. `requests` is forbidden in `src/csm/`. The `ParquetStore` is a documented exception (synchronous pyarrow I/O, which is CPU-bound local file operations, not network I/O).
- **No `print`:** use `logging.getLogger(__name__)` in `src/csm/`.
- **Logging:** structured logging with extra context dicts; never log secrets. The `install_key_redaction` filter in `api/logging.py` automatically redacts the configured API key.
- **Timezone:** `pandas.Timestamp` stored as UTC internally; `Asia/Bangkok` at I/O boundaries.

For the full standard, see `.claude/knowledge/project-skill.md` and `.claude/knowledge/coding-standards.md`.

---

## Test layout

```
tests/
├── unit/                          # Mirrors src/csm/ layout
│   ├── data/                      #   tests for src/csm/data/
│   ├── features/                  #   tests for src/csm/features/
│   ├── portfolio/                 #   tests for src/csm/portfolio/
│   ├── research/                  #   tests for src/csm/research/
│   ├── risk/                      #   tests for src/csm/risk/
│   └── scripts/                   #   tests for scripts/_export_models.py
├── integration/                   # Boundary-crossing tests
│   ├── test_public_data_boundary_files.py
│   ├── test_public_data_boundary_api.py
│   └── ...
└── api/                           # API-level tests
    ├── middleware/
    │   └── test_auth.py           # X-API-Key auth tests
    └── routers/
        └── ...
```

- **Unit tests** test one module in isolation. Use real small DataFrames. No network calls.
- **Integration tests** test boundaries: public-mode data audit, API response shapes, job lifecycle.
- **API tests** test middleware and router behaviour via `httpx.AsyncClient` or `TestClient`.
- `pytest_asyncio_mode = "auto"` is configured in `pyproject.toml` — async test functions are detected automatically.

---

## Testing security paths

The `api/security.py` middleware is tested in `tests/api/middleware/test_auth.py` (or equivalent). Key patterns:

### Testing private-mode auth

```python
import pytest
from fastapi.testclient import TestClient

def test_missing_api_key_returns_401(monkeypatch):
    monkeypatch.setenv("CSM_API_KEY", "test-secret-key")
    monkeypatch.setenv("CSM_PUBLIC_MODE", "false")
    # Reload settings or use app with patched sys.modules
    response = client.post("/api/v1/data/refresh")
    assert response.status_code == 401
    assert "Missing X-API-Key header" in response.json()["detail"]

def test_invalid_api_key_returns_401(monkeypatch):
    monkeypatch.setenv("CSM_API_KEY", "test-secret-key")
    monkeypatch.setenv("CSM_PUBLIC_MODE", "false")
    response = client.post(
        "/api/v1/data/refresh",
        headers={"X-API-Key": "wrong-key"}
    )
    assert response.status_code == 401
    assert "Invalid X-API-Key header" in response.json()["detail"]
```

### Testing public-mode 403

```python
def test_write_endpoint_blocked_in_public_mode():
    # CSM_PUBLIC_MODE=true is the default in the Docker image
    response = client.post("/api/v1/data/refresh")
    assert response.status_code == 403
    body = response.json()
    assert body["type"] == "tag:csm-set,2026:problem/public-mode-disabled"
    assert "request_id" in body
```

### Testing with the sys.modules patch pattern

The `APIKeyMiddleware` reads settings from `sys.modules['csm.config.settings'].settings` rather than from the import-time binding. This allows test fixtures to patch the settings without touching environment variables:

```python
import sys
from csm.config.settings import Settings

def test_with_patched_settings(monkeypatch):
    custom = Settings(api_key="test", public_mode=False)
    monkeypatch.setitem(sys.modules, "csm.config.settings", type(sys.modules["csm.config.settings"]))
    # ... set up client and make requests
```

---

## Local dev tips

### VS Code

Recommended extensions: Python, Ruff, Mypy Type Checker. Configure:

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.analysis.typeCheckingMode": "strict",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  }
}
```

### Debugging the API

```bash
uv run uvicorn api.main:app --reload --port 8000 --log-level debug
```

Set `CSM_LOG_LEVEL=DEBUG` in `.env` for verbose structured logging including request IDs.

### Running a single test

```bash
uv run pytest tests/unit/research/test_ranking.py::test_rank_all -v
```

### Running a single notebook

```bash
uv run jupyter notebook notebooks/02_signal_research.ipynb
```

### Before pushing

Run the full quality gate. The same commands will execute in CI — if it passes locally, it will pass in CI.
