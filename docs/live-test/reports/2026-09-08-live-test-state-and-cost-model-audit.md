# Live-test state and cost-model audit — 2026-09-08

**Scope:** backlog ownership, the live test's measured state after four months, and this repo's
transaction-cost model checked against the umbrella's canonical fee schedule.
**Method:** measurement. Nothing was re-run, re-fitted or re-evaluated, and nothing in the live path
was modified.

> ⚠️ **This is NOT the Phase C slippage audit** that
> [`docs/plans/live-test/PLAN.md`](../../plans/live-test/PLAN.md) §C requires at
> `docs/live-test/reports/slippage-audit.md`. That one must compare `ExecutionSimulator` estimates
> against **actual SET bid-ask spread data**, which this session did not fetch. See [[TK-0571]].

**Evidence tags.** Every figure carries one: `[DB]` queried from Postgres · `[FILE]` read from a
committed file · `[PROBE]` observed from the running system · `[GIT]` from commit history ·
`[BOARD]` from the `plans/_pm` ticket store · `[UNVERIFIED]` asserted but not established here.
Anything not established is written **NOT MEASURED — <reason>**.

---

## 0. Nothing in the live path was modified — confirmed

| Check | Result |
|---|---|
| `git -C strategies/csm-set status --porcelain` before this report | empty `[GIT]` |
| Files changed by this work | `docs/live-test/` only — no `src/`, `configs/`, `scripts/`, `.env` `[GIT]` |
| Container | `csm-set-csm-1` never stopped, restarted or recreated; `RestartCount 0`, started 2026-09-01T14:09:59Z `[PROBE]` |
| Docker verbs used | `exec … psql`, `logs`, `inspect`, `ps` — all read-only `[PROBE]` |
| Orders | none placed, modified or cancelled. **This strategy holds no broker credential**, so it has no order path to use `[FILE]` |
| Database | `SELECT` only `[DB]` |

---

## 1. Backlog ownership

`owner: "unassigned"` is the literal ownerless marker. `owner` is in the schema's `required` array,
so an **absent** key is a validation failure, not an ownerless ticket `[FILE plans/_pm/schema/ticket.schema.json]`.

### Six ownerless — all claimed

Claimed to **`session:cash-carry`**, the label the routing table already assigns to
`strategies/csm-set` (at ⚠️MED-LOW confidence, on strategy-adjacency alone)
`[FILE plans/_pm/CROSS_SESSION_PROTOCOL.md:82]`. There is no csm-set session: the tmux registry
lists nine windows and none is csm-set `[PROBE]`. **The claim was made on operator instruction by a
session that is not cash-carry's own** — provenance recorded in `plans/_pm/log/2026-09/` so the
⚠️MED-LOW marker does not silently become a ✅.

| Ticket | Type | What it is | Disposition |
|---|---|---|---|
| **TK-0294** | bug | `sector_rel_strength` is population-dependent — universe size silently changes the composite ranking | **CLAIMED** — the signal item, §4 |
| **TK-0296** | decision | Production pins `CSM_OHLCV_SOURCE=parquet`, the path `Settings` marks deprecated | **CLAIMED** — 🔴 its condition has already fired |
| **TK-0298** | bug | `signal_snapshots` upsert key carries wall-clock time — 72 docs, 72 keys, never collides | **CLAIMED** |
| **TK-0283** | bug | Six settings tests fail on any host with a populated `.env` | **CLAIMED** |
| **TK-0297** | bug | Mixed-basis risk is the gateway's unbounded equity-curve read, not the CAGG | **CLAIMED** |
| **TK-0489** | task | `daily_return` backfill-vs-cutover, 112 legacy rows | **CLAIMED** — filed under `feature-strategies-report-metrics`, csm-set in substance |

All six were `status: open` and **untouched for 21 days** at the time of claiming `[GIT]`.

🔴 **TK-0296's condition has already expired.** Its `due:` reads
`condition:decide before the September ranking` `[BOARD]`. The September ranking ran on
**2026-08-31**; today is 2026-09-08. A condition-gated ticket whose condition fires unobserved is
invisible to every date-based sweep, which is the documented blind spot in `query.py`'s own docstring.

### Three NOT mine — routed, not claimed

`owner: "session:pm"`. The pre-push guard reads the **pre-push** owner, so editing these is refused
`[FILE plans/_pm/lib/ownership.py]`. They are `session:pm`'s because the operator directly instructed
their publication there on 2026-08-10 `[BOARD]`.

| Ticket | What it is | Where it belongs |
|---|---|---|
| **TK-0278** | 🔴 P1 — the 2026-08-03 rebalance sized against a stale indicative and used an ATO market order; 15,042.65 THB = **1.21% of NAV** | `session:pm`. **The highest-leverage live csm-set item, and it is not this session's to move.** |
| **TK-0279** | Do the 35% sector cap and 5–15% position bound bind on **drift** or only at **construction**? | `session:pm` |
| **TK-0285** | `POST /api/v1/data/refresh` writes to the wrong path and never passes `adjustment` | `session:pm` |

⚠️ **TK-0285 contradicts itself, and the contradiction is the lesson.** Its `due:` says
*"➡️ ROUTED 2026-08-18 to session:cash-carry … session:pm is no longer carrying it"*, while
`TK-0285.md:8` still reads `owner: "session:pm"` `[BOARD]`. **Routing lives in prose; ownership lives
in the field; only the field is enforced.** So the ticket is *not* claimable despite what it says
about itself. Correcting it requires a change-request issue against `session:pm`'s label — not an
edit — and none was opened, because the routing is that session's decision to restate.

### The "seven alpha items" premise — NOT REPRODUCIBLE

I was told one ownerless ticket is *"among only seven items on the whole board that generate or
validate alpha."* **No ticket field encodes alpha.** The schema sets `additionalProperties: false`
and permits exactly twelve keys — no `tags`, no `labels`, no `category`, no `priority`
`[FILE plans/_pm/schema/ticket.schema.json]`. Grepping `alpha` across all 577 ticket files returns 19
prose hits and no inventory `[BOARD]`.

The nearest real mechanism is `ALPHA_FIRST_TAGS = ("strategy", "alpha")` in the PM scanner
`[FILE .claude/skills/project-manager/scripts/scan.py:97]`, which substring-matches **feature slugs**,
not tickets. Deriving from that gives exactly seven live items under
`feature: strategy-microstructure-research` — **and none of those seven is a csm-set ticket** `[BOARD]`.

⇒ **Treat "seven alpha items" as an unverified upstream assertion.** The signal-level item is real
and is identified in §4; the set it was said to belong to is not.

---

## 2. What the live test actually shows

### Running, on which node, on which broker account

| | |
|---|---|
| Container | `csm-set-csm-1`, **Up 6 days (healthy)**, `RestartCount 0` `[PROBE]` |
| Health | `scheduler_running: true`, `last_refresh_status: succeeded`, `postgres/mongo/gateway: ok` `[PROBE]` |
| Node | **HOME** — `ubuntu-docker`, 192.168.1.13; host port `:8100` `[PROBE]` |
| Broker account | **NONE.** `.env` carries no broker credential of any kind `[FILE]` |

**The strategy has no execution path.** It generates a recommended book; the operator places the ATO
orders manually at Settrade click2win and hand-enters the fills into `configs/live_portfolio.yaml`
`[FILE docs/live-test/monthly/2026-07.md:304]`. It is not routed through `quant-execution-engine`, it
holds no Liberator or Streaming Pro session, and the ONE-BROKER-ACCOUNT-PER-NODE rule does not reach
it.

⚠️ **[UNVERIFIED] — an unresolved contradiction, recorded not resolved.** The monthly reviews say
*"This review covers paper-trading only"* in the same sentence as *"the operator places the ATO
orders via settrade click2win and updates `configs/live_portfolio.yaml` **after** fills confirm"*
`[FILE]`. Real fill prices, real commission at a real rate, and two capital injections totalling
120,000 THB are booked against it. **Whether that Settrade account is a paper account or a funded one
is not establishable from this tree**, and it changes what the whole live test means. It needs an
operator answer, not an inference.

### 86 trading days, 2026-05-04 → 2026-09-07

| Store | Rows | Range |
|---|---|---|
| `db_gateway.daily_performance` | **86** rows / 86 distinct dates | 2026-05-04 → 2026-09-07 `[DB]` |
| `db_csm_set.equity_curve` | **85** rows / 85 dates, 0 non-midnight | 2026-05-05 → 2026-09-07 `[DB]` |
| `db_gateway.strategy_report_snapshot` | 72 rows | 2026-05-22 → 2026-09-07 `[DB]` |
| `docs/live-test/daily/*.md` | **86** logs | 2026-05-04 → 2026-09-07 `[FILE]` |

91 weekdays fall in that window; the five with no row are exactly the SET holidays
(2026-06-01, 06-03, 07-28, 07-29, 08-12) `[DB][FILE]`. **Data completeness 100%.** `equity_curve`
starts one day later because 2026-05-04 is the entry day and the first fills were 2026-05-05 ATO.

### A pre-test expectation WAS registered

**Yes — and before the test started.** Commit `a0b673a`, **2026-05-04 12:29:56 +07**, carries the
full "Metrics & Success Criteria" section: six primary metrics with targets and warning thresholds,
plus eight production-readiness criteria `[GIT][FILE]`. The live-test kickoff commit `24aa62d` is
**37 minutes later**, and the first fill was the next day `[GIT]`. The eight criteria are byte-identical
in that first commit and today `[GIT]`.

Measured against them, at Day 86 of a planned 8 months:

| # | Pre-registered metric | Target | Measured (flows stripped) | Verdict |
|---|---|---|---|---|
| 1 | Cumulative return | positive, within 3pp of backtest | **+15.6885%** `[DB]` | ✅ on sign; see §3 on the baseline |
| 2 | Sharpe since inception | ≥ 0.5 | **1.6164** (n=85) `[DB]` | ✅ |
| 3 | Maximum drawdown | > −15% | **−7.1073%** on 2026-07-30 `[DB]` | ✅ |
| — | Annualized volatility | **≤ 15%**, warn > 20% | **29.3897%** `[DB]` | 🔴 **BREACH — ~2× target** |
| 4 | Live vs backtest return gap | ± 5pp | **NOT MEASURABLE** | ⚠️ see below |
| 5 | Data completeness | ≥ 95% | **100%** (86/86) `[DB]` | ✅ |
| 6 | System uptime | ≥ 99% | **NOT MEASURED** — no uptime series is banked; the daily logs assert it per-session but nothing aggregates it | ⚠️ |
| 7 | No unexplained model deviations | zero | **NOT MEASURED** — three model-deviation events are filed and all three are *explained*, which is not the same as zero `[FILE]` | ⚠️ |
| 8 | Circuit-breaker behaviour matches design | trips on real DD | **NOT EXERCISED** — it has never tripped. Closest approach was the **−7.1073%** drawdown on 2026-07-30 against a −10% trigger, a margin of **2.8927pp** `[DB]`. A criterion that requires the breaker to trip **cannot be met by a test in which it does not** | ⚠️ |

#### 🔴 The volatility breach is the finding

Realized annualized volatility is **29.3897%** against a pre-registered target of **≤15%** and a
warning threshold of **>20%** `[DB]`. The strategy runs a **15% annual vol-target overlay**
(`overlays.vol_scaling.target_annual: 0.15`) `[FILE]` and realizes very close to double it.

**It has never been reported, and the reason is structural: volatility is absent from the live-test
README's tracked-metrics table** `[FILE docs/live-test/README.md]`. That table carries NAV, monthly
return, total return, realized/unrealized P/L, commission, Sharpe, max drawdown, data completeness,
uptime and the position bound — **but not the one primary metric that is in breach.** A metric
nobody renders is a metric nobody checks. Filed as [[TK-0564]].

#### ⚠️ The published Sharpe counts capital injections as returns

The README reports **Sharpe 2.69 (annualized, n=80)** `[FILE]`. That reproduces to four decimals —
**2.6940** — only when the +100,000 and +20,000 THB injections are treated as investment returns
`[DB]`. Stripping the flows gives **1.9298** over the same window.

| n=80, to 2026-08-31 | Sharpe | Ann. vol |
|---|---:|---:|
| Flows counted as return (**the published basis**) | **2.6940** | 34.4329% |
| Flows stripped (correct) | **1.9298** | 29.3174% |

**The verdict on criterion 2 does not change** — both clear 0.5 comfortably. The number does, by 40%,
and the same defect inflates volatility by 5.1pp. The daily logs handle the injections correctly and
say so repeatedly; the README's summary block does not. Filed as [[TK-0568]].

#### ⚠️ Criterion 4 has no usable baseline

The criterion is *"live vs backtest return gap within ±5pp"*. Two backtest baselines were registered
on the same day `[FILE docs/plans/live-test/PLAN.md:216]`:

| Baseline | CAGR | Sharpe | Max DD | Data | Config |
|---|---:|---:|---:|---|---|
| Phase 3.8 | 12.52% | 0.663 | −31.03% | **real SET, 2009–2026** | broad book, institutional |
| Phase 4.9 | 36.24% | 2.70 | −10.54% | **synthetic** | **the config that is live** |

**The live book runs Phase 4.9's configuration, whose numbers are synthetic-data only. The real-data
numbers belong to a configuration that is not live.** Every monthly review compares against Phase 3.8
anyway `[FILE]`. This is a pre-registration defect, not a measurement one, and it must be settled
before Phase D rather than at it. Filed as [[TK-0570]].

### Six comparability breaks, all inside the 86 days

| Date | Break | Effect |
|---|---|---|
| 2026-06-04, 2026-08-03 | Capital injections +100,000 / +20,000; `starting_nav` rebased 1,000,000 → 1,100,000 → 1,120,000 `[FILE]` | Any return series must strip the flows. The README's Sharpe does not |
| 2026-08-01 | Universe regenerated with sector carried through (`52e9830`); the August rebalance was **amended after publication** `[GIT]` | The published trade list changed |
| **2026-08-09** | **The price-adjustment kwarg had never been passed. Every momentum factor for the first three months ran on split-adjusted-only prices** (`e04a292`, [[TK-0277]]) `[GIT][FILE]` | 🔴 **Splits the factor history in two.** The selection was shown unchanged, but the input basis before and after 08-09 is not the same quantity |
| 2026-08-24 → 08-31 | Four ex-dividend restatements rewrote banked price history; one reported sign flipped `[FILE]` | **Open — characterised, not fixed** |
| 2026-09-01 | Dual-bar NAV corruption zeroed 7 of 10 holdings; headline NAV read 373,561.70 against a true 1,273,881.70, and one `equity_curve` row was destroyed `[FILE]` | Fixed, deployed and repaired |
| 2026-09-02/03 | Gateway `daily_return` denominator corrected `[FILE]` | **112 rows remain on the legacy basis** ([[TK-0489]]) |

Config itself is stable: `configs/live-settings.yaml` has not changed since **2026-05-05** and
`configs/live_portfolio.yaml` only at the four rebalances `[GIT]`. **The instability is in the data
and the reporting layer, not in the parameters.**

### Durable, or only rendered? — both, and the split is the finding

| Recorded durably | Only rendered into prose |
|---|---|
| NAV — `daily_performance` 86 rows `[DB]` | **Every trade the strategy has ever made** |
| Equity — `equity_curve` 85 rows `[DB]` | The commission ledger (hand-maintained markdown table) |
| P/L series — `docs/live-test/graphs/pnl.csv`, 85 rows, git-tracked `[FILE]` | Slippage — measured **once**, in one markdown table |
| Positions + `avg_cost` — `configs/live_portfolio.yaml` `[FILE]` | Realized P/L per closed name |

🔴 **`db_csm_set.trade_history` holds 0 rows after four rebalances** `[DB]`. `backtest_log` and
`benchmark_equity_curve` are empty too — **of five tables in `db_csm_set`, only `equity_curve` has
ever been written** `[DB]`.

The cause is two hardcoded literals: `src/csm/adapters/hooks.py:243` and `:483` both pass
`trades=[]`, with the comment *"Phase 1: trade-pairing requires historical fill stream"* `[FILE]`.
So every daily gateway payload reports:

```
"commission_paid": "0"   "total_trades": 0   "net_pnl": "0"   "trades": []
```

`[DB]` — while the book has actually paid **3,735.16 THB** in commission `[FILE]`. `sharpe_ratio`
likewise reads **0 in 76 of 86 rows** `[DB]`. **The platform's own record of this strategy says it has
never traded and never paid a fee.** Filed as [[TK-0565]].

---

## 3. The cost model

### There are three, and they do not touch each other

| # | Model | Location | Ever moves a number? |
|---|---|---|---|
| **A** | Flat `transaction_cost_bps = 15.0` × one-way turnover | `src/csm/config/constants.py:72`, `src/csm/research/backtest.py:145`, applied at `:710` | ✅ **The only one** |
| **B** | Square-root impact slippage | `src/csm/execution/slippage.py`, `simulator.py` | ❌ **Zero production callers** |
| **C** | Thai broker fee stack, 0.16799% per side | `configs/live-settings.yaml:89-100` | ❌ **No code reads this file** |

Model A is the whole of the executable cost model:

```python
cost: float = turnover * (config.transaction_cost_bps / 10_000.0)
nav *= 1.0 + gross_return - cost          # backtest.py:710
```

with `turnover = 0.5 * Σ|Δw|`, one-way `[FILE src/csm/portfolio/rebalance.py:26]`.

### Component by component

| Component | Value | Unit | Kind | Live? |
|---|---:|---|---|---|
| Commission | 0.0015 | fraction of trade value | constant | ❌ inert YAML |
| SET trading fee | 0.00005 | fraction | constant | ❌ inert YAML |
| TSD clearing | 0.00001 | fraction | constant | ❌ inert YAML |
| Regulatory | 0.00001 | fraction | constant | ❌ inert YAML |
| VAT | 0.07 | fraction of the sum | constant | ❌ inert YAML |
| **All-in per side** | **0.16799% = 16.799 bps** | | 🧮 derived | **applied BY HAND** |
| Half-spread | 10.0 | bps | parameter, default | ❌ never called |
| Impact coefficient | 10.0 | bps per √participation | parameter, default | ❌ never called |
| **Commission (code)** | **`Decimal("0")`** | THB | **default** | reachable, never fed |
| **Lumped backtest cost** | **15.0** | **bps on one-way turnover** | constant | ✅ **the only live one** |

Arithmetic check: `(0.0015 + 0.00005 + 0.00001 + 0.00001) × 1.07 = 0.0016799` `[FILE]`, which is the
0.16799% every live-test doc quotes.

**Spread and impact are not charged anywhere.** Model B computes
`slippage_bps = half_spread_bps + impact_coef × √(notional/ADTV)` and **reports** it on a `TradeList`;
no code path deducts it from any return `[FILE src/csm/execution/simulator.py:141-192]`.

### The commission default of zero — CONFIRMED, with a correction

`src/csm/execution/trade_pairing.py:53` `[FILE]`:

```python
commission: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
```

docstring line 43: *"Per-fill commission in THB; defaults to zero."* And `ExecutionConfig` has **no
commission field at all** — commission is not zero there, it is absent `[FILE simulator.py:30-40]`.

**Is it on a live path?** `src/csm/adapters/hooks.py:30` imports `ClosedTrade` from that module, so
yes, the live path reaches it. **But the default is never exercised**, because the live path feeds it
a hardcoded empty list (§2). The reported `commission_paid: "0"` in every gateway row comes from
`sum(() , start=ZERO)` over zero trades, not from a fill that defaulted `[FILE]`.

⇒ **The zero default is real and is not what produced the zeros. The absence of a trade record is.**
That is a worse finding, not a milder one: a defaulted fee is a wrong number, whereas no fill stream
at all means the pairing code, the realized-P/L path and the commission column have **never executed
against live data** in 86 sessions.

### ⚠️ `configs/live-settings.yaml` has no code consumer

Exhaustively: the repo contains exactly two YAML loads, and both read `live_portfolio.yaml`
`[FILE src/csm/live/portfolio.py:125, scripts/compare_adjustment_ranking.py:118]`. Nothing loads
`live-settings.yaml`. Its fee block, slippage model, vol target, circuit-breaker thresholds, sector
cap and position bounds are **documentation of what the code defaults are believed to be, not inputs
to anything.**

**This is already live drift, not a theoretical risk.** The container runs
`CSM_REFRESH_CRON=0 18 * * 1-5` while the YAML says `refresh_cron: "30 13 * * 1-5"` — 18:00 BKK
against 20:30 BKK `[PROBE][FILE]`. The env var wins because the YAML is not read.

Three documents assert otherwise:

- `docs/plans/live-test/PLAN.md:99` — *"`configs/live-settings.yaml` as Single Source of Truth … The
  YAML file is the operator's control panel: change parameters without touching code."* **False.**
- `docs/live-test/graphs/README.md:126` — the fee rate is *"Defined in `configs/live-settings.yaml`
  (`execution.fees`) and **applied at every fill**."* True of the human bookkeeping; **false of code.**
- `scripts/build_rationale_notebook.py:814` — every generated rationale notebook tells its reader the
  configuration is *"specified in `configs/live-settings.yaml`"*. **False, and it ships to readers.**

Filed as [[TK-0566]].

### 🐛 `ExecutionConfig.slippage_model` is a silent no-op

Declared at `simulator.py:36-38`, then ignored: `__init__` at `:50-51` constructs
`SqrtImpactSlippageModel()` with no config and `simulate()` never reads `config.slippage_model`
`[FILE]`. So `ExecutionConfig(slippage_model=SlippageModelConfig(half_spread_bps=20.0))` stores the
value and changes nothing. The unit test asserts only that the field round-trips on the config object,
never that `simulate()` honours it `[FILE tests/unit/execution/test_execution_simulation.py:124-141]`.
Filed as [[TK-0569]].

### Against the canonical fee schedule

🔴 **csm-set cannot adopt it today. SET cash equities is an explicit GAP, not a covered class.**

The canonical schedule
(`quant-execution-engine/src/quant_execution_engine/reference/fee_schedule.toml`, mirrored to
`docs/reference/fee-schedule.md`, both dated **2026-09-04**) covers **only TFEX SET50 index futures
and options, broker `liberator`** `[FILE]`. Its Gap 2 names this repo's own config as the thing that
does not reach the bar:

> **`set_equities` / "SET listed equities"** — what exists: `commission 0.0015 ; tsd_clearing 0.00001
> ; vat_rate 0.07`, where: `strategies/csm-set/configs/live-settings.yaml`. **Why not canonical: "A
> configuration default carrying NO stated source of any kind."**

⚠️ **The gap record is itself incomplete** — it lists three of the five fee lines and omits
`set_trading: 0.00005` and `regulatory: 0.00001` `[FILE]`. The omission understates csm-set's own
rate, so the gap's comparison is drawn against the wrong figure. Worth correcting at the source,
which is another session's file.

**Per component, in currency and in the strategy's own unit.** The only venue-quoted SET-equity
figures the platform has ever had come from a single Liberator pre-place observation (PTT 100 @ 35.00,
2026-09-04), which the schedule records and **explicitly refuses to canonicalise** — *"one
observation cannot make it so … one notional, one symbol, one side, one day"* `[FILE]`.

| Component | csm-set | Venue observation (n=1, non-canonical) | Canonical schedule | Gap |
|---|---:|---:|---|---|
| Commission, ex-VAT | 0.150000% | 0.049933% | **GAP** | csm-set **3.00×** |
| Regulatory/other, ex-VAT | 0.007000% | 0.006943% | **GAP** | +0.8% |
| VAT | 7% | folded into each line | **GAP** | — |
| **All-in per side** | **0.16799%** | **0.060857%** | **GAP** | csm-set **2.76×** |
| **All-in per side, bps** | **16.799 bps** | **6.0857 bps** | **GAP** | **+10.713 bps** |

**In the strategy's own unit — bps charged on one-way turnover, which is what model A reasons in:**

| Reference | bps of one-way turnover | vs model A's 15.0 |
|---|---:|---|
| **Model A — what the backtest actually charges** | **15.000** | — |
| Round trip at csm-set's own documented fee rate | **33.598** | model covers **44.6%**, short **18.598 bps** |
| Round trip at the venue observation | **12.171** | model **over**charges by **2.829 bps** |
| **Realized on 2026-08-03, fees + slippage** | **740.36** | model covers **2.0%** |

🔑 **The sign of the fee error depends on which reference you pick, and the two disagree.** Against
the repo's own documented rate the model **undercharges by 2.2399×**; against the venue observation
it **overcharges by 1.23×**. In THB across the whole live test: actual commission **3,735.16**
(0.2893% of NAV) against a modelled **1,667.58** (0.1292%) `[FILE]`.

**This is the opposite direction from the defect that invalidated the other study.** That one charged
**3.76×** the operator's real cost — overstating, and it killed a strategy family that may have been
viable. csm-set's YAML rate also overstates relative to the venue observation (2.76×), which the
schedule calls *"the SAFE error: a strategy priced with it looks worse than reality"* `[FILE]`.

**But fees are not the material term here.** On the one rebalance where friction was actually
measured `[FILE docs/live-test/daily/2026-08-03.md]`:

| | THB | bps of one-way turnover |
|---|---:|---:|
| Fees | 682.65 | 33.598 |
| **Slippage (mark-to-close)** | **14,360.00** | **706.76** |
| **Total friction** | **15,042.65** | **740.36** |
| What model A would have charged | 304.77 | 15.000 |

**Slippage was 21× the commission**, and the lumped 15 bps — which is meant to stand for fees *and*
slippage together — covered **2.0%** of it. Arguing about a 1.8 bps fee difference while the
unmodelled term is 707 bps is arguing about the wrong number. Filed as [[TK-0567]].

### Was the cost error load-bearing? — the verdict

**Distinguishing gated from computed, as asked:**

| Conclusion | Cost gated it? | Load-bearing? |
|---|---|---|
| Every live-test NAV, return, Sharpe, drawdown figure | **No.** NAV is computed from actual broker fills; the modelled cost never enters `[FILE]` | **NO** |
| Rebalance decisions (4 of them, incl. the 2026-08-31 no-trade) | **No.** Decided by rank floor, buffer and EMA100 `[FILE]` | **NO** |
| Candidate filtering | **No.** ADTV, earnings, margin, rank percentile — no cost term `[FILE]` | **NO** |
| The walk-forward gate | **No.** `walkforward_gate.py` thresholds are Sharpe-only; cost is upstream of the Sharpe but never the gated quantity `[FILE]` | **NO** |
| **Phase 3 / 3.5 / 3.6 backtest sign-off** | **YES** — `Sharpe @20bps > 0.5`, in `notebooks/03_backtest_analysis.ipynb` `[FILE]` | **YES — this is what authorized the live test to exist** |
| **Criteria 1 and 4 (Phase D)** | **YES, prospectively** — both measure against the 12.52% CAGR baseline model A produced at 15 bps | **YES, but not yet evaluated** |

**Verdict: the cost model was NOT load-bearing on anything the live test has concluded.** The live
test measures a real book with real fees hand-applied; the modelled cost is not in that path at all.

**It WAS load-bearing on the decision to run the strategy**, and it **will be** on two of the eight
production-readiness criteria, which are due Nov–Dec 2026 and have not been evaluated.

⚠️ The stored outputs of those sign-off cells already record failures — `❌ FAIL Max Recovery @15bps`
and `❌ FAIL Turnover @20bps (250%) ≤ 180%`, with `❌❌❌ PHASE 3.5 INCOMPLETE` and
`❌❌❌ PHASE 3.6 INCOMPLETE` `[FILE]`. (The recovery figures print as `37.9M`, a THB value compared
against a months threshold, so treat those two as an unreliable unit bug; the Sharpe and turnover
gates are well-formed.)

### What would need revisiting — no re-run performed, and none proposed here

1. The **Phase 3.8 baseline** (CAGR 12.52% / Sharpe 0.663 / MaxDD −31.03%) at a defensible cost basis.
2. The **Phase 3/3.5/3.6 sign-off verdicts**, which are the only cost-gated conclusions in the repo.
3. **Criteria 1 and 4** before Phase D, not at it — and only after [[TK-0570]] settles which baseline
   they measure against.
4. **The `37.9M` recovery figure's units**, which make two recorded FAILs uninterpretable.

**None of this can proceed on the canonical schedule as it stands.** Adopting it for csm-set requires
closing its `set_equities` gap, and the schedule states what that takes: *"the broker's published
equity schedule, OR a repeated observation series across notionals … that separates a flat rate from
a rate-with-minimum"* `[FILE]`. **That is a gap to close, not a number to invent here.**

---

## 4. The alpha item — [[TK-0294]]

Of the six ownerless tickets, five are engineering. **TK-0294 is signal-level**: it is about whether
the ranking that picks the portfolio is a stable function of the prices.

**The defect.** `src/csm/features/sector.py:38` computes
`sector_rel_strength = mom_12_1(symbol) − mom_12_1(sector)`, where the sector composite is built from
**whatever symbols were passed to `build()`**. Universe size therefore moves every sector's mean, and
the composite that `construction.select()` ranks on moves with it `[BOARD]`.

**Actual state: open, filed 2026-08-11 by `session:pm`, measured rather than asserted, untouched for
28 days, zero log entries** `[BOARD][GIT]`. It was found while verifying the [[TK-0277]] re-rank — a
by-product, not a search.

**The measurement, from the ticket.** Two honest 204-symbol builds of the 2026-07-31 cross-section,
identical code, identical adjustment `[BOARD]`:

| Factor | Differs? | Correlation |
|---|---|---:|
| The five pure momentum factors | **No** — identical to 0.000000 | 1.000000 |
| `residual_momentum` | **Yes, on all 204** | 0.9296 |
| `sector_rel_strength` | **Yes, on all 204** | 0.9913 |

**Not stale, not superseded.** It describes a standing property of code that has not changed
`[GIT]`. Its sibling `src/csm/features/risk_adjusted.py:121-122` carries the same defect.

**What it needs to move — a decision, not a fix.** Either:

- **(a) Make the factor universe-invariant** — pin the sector composite to a fixed constituent set
  (e.g. the SET sector index) so it stops depending on who happened to be fetched; or
- **(b) Accept the dependency and freeze its input** — pin the refresh's universe filter and bar
  count as part of the frozen live-test config, and record that the factor is only comparable within
  a fixed universe.

(a) is correct and is a code change during a code freeze. (b) is cheap and is what the live test has
been implicitly doing without saying so. **The choice belongs to the operator.**

⚠️ **Its guard condition has already fired twice, unobserved.** The `due:` reads
`condition:before any change to the refresh's universe filter or bar count` `[BOARD]`. Two such
changes have landed since it was filed: the **2026-08-01** universe regeneration (`52e9830`, which
also amended a published trade list) and the **2026-08-09** price-adjustment fix (`e04a292`, which
changed every input price) `[GIT]`. **The condition it was waiting for is in the past, and nothing
noticed** — which is the same blind spot that TK-0296's expired September deadline shows.

⇒ **Both signal-adjacent tickets are gated on conditions that have already occurred.** That is the
practical cost of a backlog with no owner: condition-gated work does not age into visibility, it ages
out of it.

---

## Ticket outcomes

**Claimed to `session:cash-carry`:** [[TK-0283]] · [[TK-0294]] · [[TK-0296]] · [[TK-0297]] ·
[[TK-0298]] · [[TK-0489]]

**Routed, not editable** (`session:pm`): [[TK-0278]] · [[TK-0279]] · [[TK-0285]]

**Filed by this report:** [[TK-0564]] volatility breach · [[TK-0565]] zero trades and zero commission
reported · [[TK-0566]] inert `live-settings.yaml` · [[TK-0567]] 15 bps under-covers fees alone ·
[[TK-0568]] injection-inflated Sharpe · [[TK-0569]] dead `slippage_model` parameter ·
[[TK-0570]] ambiguous criterion-4 baseline · [[TK-0571]] Phase C slippage audit outstanding
