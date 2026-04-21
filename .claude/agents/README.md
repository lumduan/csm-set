# Claude Agents for csm-set

Specialized sub-agents for the Cross-Sectional Momentum (csm-set) project.

## Available Agents

| Agent | Purpose |
|---|---|
| `@python-architect` | Architecture, async patterns, type safety, code quality |
| `@dependency-manager` | uv package management, dependency updates, environment setup |
| `@git-commit-reviewer` | Pre-commit validation, commit message standards, repo hygiene |
| `@documentation-specialist` | Docstrings, API docs, usage examples |

## Usage

Reference an agent in your prompt to invoke its expertise:

```
@python-architect review this new signal calculation module
@dependency-manager add scikit-learn to the research group
@git-commit-reviewer prepare a commit for the backtest changes
@documentation-specialist add docstrings to src/csm/signals.py
```
