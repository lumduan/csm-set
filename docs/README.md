# Documentation Index

`docs/` is the central documentation tree for csm-set. Every page is written in English and is designed to be usable by both human readers and AI/LLM coding agents.

## Directory map

| Directory | Purpose |
|-----------|---------|
| `getting-started/` | Docker + uv quickstart; first-contact endpoints |
| `architecture/` | Monorepo layer map, data flow, security model, config reference |
| `concepts/` | Deep dives: cross-sectional momentum theory, SET constraints |
| `guides/` | Operational how-tos: Docker recipes, public-mode rules |
| `development/` | Contributor workflow, quality gate, commit conventions |
| `reference/` | Per-subpackage API surface (data, features, portfolio, research, risk, execution) |
| `plans/` | Master roadmap and per-phase implementation plans (git-tracked) |

## Key pages

- [Getting Started](getting-started/overview.md) — run the project in under 5 minutes
- [Architecture Overview](architecture/overview.md) — layers, data flow, public-mode boundary
- [Docker Guide](guides/docker.md) — compose recipes, healthcheck, CORS, troubleshooting
- [Public Mode Guide](guides/public-mode.md) — data boundary, 403 contract, owner workflow
- [Momentum Concept](concepts/momentum.md) — Jegadeesh–Titman theory and SET implementation
- [Development Guide](development/overview.md) — workflow, quality gate, commit conventions

## Reference pages

Per-subpackage module index with public callables, signatures, and cross-references:

- [Data Layer](reference/data/overview.md) — `loader`, `store`, `universe`, `cleaner`
- [Features](reference/features/overview.md) — `momentum`, `risk_adjusted`, `sector`, `pipeline`
- [Portfolio](reference/portfolio/overview.md) — `optimizer`, `construction`, `rebalance`
- [Research](reference/research/overview.md) — `ranking`, `ic_analysis`, `backtest`
- [Risk](reference/risk/overview.md) — `metrics`, `regime`, `drawdown`
- [Execution](reference/execution/overview.md) — `simulator`, `slippage`, `trade_list`

## Plans

All implementation plans are tracked under `docs/plans/`, organised by phase:

- [Master Roadmap](plans/ROADMAP.md) — high-level project phases and milestones
- Phase 1–6 plans — completed implementation records
- [Phase 7: Hardening & Documentation](plans/phase_7_docs/PLAN.md) — current phase (in progress)
