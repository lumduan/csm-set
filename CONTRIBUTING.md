# Contributing to csm-set

Thank you for your interest in contributing to csm-set.

## Development Environment

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker (for integration testing)

### Setup

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set
uv sync --all-groups
uv run pre-commit install
```

Create a local `.env` file from `.env.example` before running private-mode workflows.

### Running Quality Gates

All of these must pass before opening a PR:

```bash
# Linting and formatting
uv run ruff check .
uv run ruff format --check .

# Type checking
uv run mypy src/

# Tests
uv run pytest tests/ -v --tb=short
```

### Public and Private Modes

- `CSM_PUBLIC_MODE=true`: read-only mode, no raw data fetches, no write endpoints
- `CSM_PUBLIC_MODE=false`: owner mode, live data refresh and export scripts enabled

Public mode is the default deployment mode and must remain safe for anyone who clones the repository.

### Project Structure

```
src/csm/        # library core — data, features, research, portfolio, risk
api/            # FastAPI backend
ui/             # NiceGUI dashboard
tests/          # unit + integration tests
scripts/        # owner-only data management scripts
results/        # pre-computed outputs committed to git
```

### Data Boundary Rule

**Raw OHLCV data must never enter the repository.** This is enforced at three levels:

1. `.gitignore` excludes the entire `data/` directory
2. `OHLCVLoader` raises `DataAccessError` in public mode
3. API middleware returns HTTP 403 on write endpoints in public mode

When contributing, never add any code that bypasses these checks.

### Documentation and Results

- Keep `results/` free of raw OHLCV columns or files
- Update relevant docs under `docs/` when behavior changes
- Use `scripts/export_results.py` to regenerate public artifacts

### PR Process

1. Fork the repository and create a feature branch from `main`
2. Write tests for new functionality
3. Ensure all quality gates pass
4. Update documentation and examples when relevant
5. Open a PR against `main` with a clear description of the change
6. Address review comments

### Commit Style

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add sector-relative momentum feature
fix: handle missing data in universe builder
docs: expand public mode guide
test: add IC analysis unit tests
```
