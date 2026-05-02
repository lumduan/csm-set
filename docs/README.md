# Documentation Index

Entry point for csm-set documentation. Each top-level folder has a single overview page; deeper pages are linked from within.

## Top-level directories

| Directory | Purpose |
|-----------|---------|
| [getting-started/](getting-started/overview.md) | Docker + uv quickstart; first contact with the running app |
| [architecture/](architecture/overview.md) | Layer responsibilities, data flow, public-mode boundary, security model |
| [concepts/](concepts/momentum.md) | Theoretical background: cross-sectional momentum, Jegadeesh–Titman |
| [reference/](reference/) | Per-subpackage module reference: data, features, portfolio, research, risk |
| [guides/](guides/) | Operational guides: Docker recipes, public-mode rules |
| [development/](development/overview.md) | Dev workflow, quality gate commands, commit conventions, code style |
| [plans/](plans/) | Master plans for each project phase (historical record) |

## Reference pages

- [Data Layer](reference/data/overview.md) — `src/csm/data/`: loader, store, universe, cleaner
- [Features Layer](reference/features/overview.md) — `src/csm/features/`: momentum, risk-adjusted, sector, pipeline
- [Portfolio Layer](reference/portfolio/overview.md) — `src/csm/portfolio/`: optimiser, constraints, rebalancing
- [Research Layer](reference/research/overview.md) — `src/csm/research/`: ranker, IC, backtest
- [Risk Layer](reference/risk/overview.md) — `src/csm/risk/`: metrics, regime detection

## Guides

- [Docker Guide](guides/docker.md) — public/private compose, healthcheck, CORS, troubleshooting
- [Public Mode Guide](guides/public-mode.md) — data boundary, 403 contract, owner workflow

## Development

- [Getting Started](getting-started/overview.md) — first-run instructions
- [Development Overview](development/overview.md) — workflow, quality gate, commit conventions
- [Architecture Overview](architecture/overview.md) — how the layers fit together
- [Momentum Concept](concepts/momentum.md) — theoretical background

## Plans

- [Master Roadmap](plans/ROADMAP.md) — project phase tracker
- [Phase 7 Plan](plans/phase_7_docs/PLAN.md) — current phase: hardening & documentation
