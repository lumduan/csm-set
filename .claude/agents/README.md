# Claude Agents for csm-set

Specialized sub-agents for the Cross-Sectional Momentum (csm-set) project.

## Available Agents

### Architecture & Code Quality
| Agent | Purpose |
|---|---|
| [`@python-architect`](python-architect.md) | Architecture, async patterns, type safety, code quality |
| [`@refactor-specialist`](refactor-specialist.md) | Behavior-preserving structural change under green tests |
| [`@api-designer`](api-designer.md) | REST / FastAPI design, schemas, versioning, OpenAPI quality |

### Engineering Workflow
| Agent | Purpose |
|---|---|
| [`@dependency-manager`](dependency-manager.md) | uv package management, dependency updates, environment setup |
| [`@git-commit-reviewer`](git-commit-reviewer.md) | Pre-commit validation, commit message standards, repo hygiene |
| [`@documentation-specialist`](documentation-specialist.md) | Docstrings, API docs, usage examples |
| [`@release-manager`](release-manager.md) | Version bumps, CHANGELOG, tagging, publish, smoke test |

### Reliability
| Agent | Purpose |
|---|---|
| [`@bug-investigator`](bug-investigator.md) | Root-cause analysis, repro-first fixes, regression tests |
| [`@test-engineer`](test-engineer.md) | pytest specialist — unit, integration, regression, property tests |
| [`@performance-optimizer`](performance-optimizer.md) | Profiling, latency, memory, pandas / async / Parquet hot paths |
| [`@security-reviewer`](security-reviewer.md) | Secrets, injection, auth, validation, dep CVEs |

## Usage

Reference an agent in your prompt to invoke its expertise:

```
@python-architect review this new signal calculation module
@dependency-manager add scikit-learn to the research group
@git-commit-reviewer prepare a commit for the backtest changes
@documentation-specialist add docstrings to src/csm/signals.py
@bug-investigator reproduce the NaN signal in PTT for 2024-12
@test-engineer add edge-case coverage for portfolio constraints
@performance-optimizer profile the daily backtest loop
@security-reviewer audit the new /v1/portfolios endpoint
@api-designer design the holdings sub-resource for v1
@refactor-specialist split src/csm/core.py into cohesive modules
@release-manager prepare v0.4.0 release
```

## Beyond Agents

The `.claude/` workspace also contains:

- [knowledge/](../knowledge/) — project-skill, architecture, coding-standards, commands, stack-decisions.
- [memory/](../memory/) — recurring-bugs, lessons-learned, anti-patterns.
- [playbooks/](../playbooks/) — feature-development, bugfix-workflow, code-review, release-checklist, dependency-upgrade.
- [templates/](../templates/) — task, PR, issue templates.

Read [knowledge/project-skill.md](../knowledge/project-skill.md) first — it defines the hard rules every agent must follow.
