# Live-Test Charts — how these are generated

_Last regenerated: **2026-08-01**, covering 2026-05-04 → 2026-07-31 (60 NAV points)._

Four PNGs, built from **three** committed input CSVs by **two** generator scripts. The three NAV
charts are **not** produced by a single run — they come from two different series via two runs of the
same script.

| PNG | Input | Script |
|---|---|---|
| `equity_curve.png` | `nav_actual.csv` | `gen_monthly_charts.py` (run 1) |
| `drawdown.png` | `nav_actual.csv` | `gen_monthly_charts.py` (run 1) |
| `monthly_returns.png` | `nav_twr.csv` | `gen_monthly_charts.py` (run 2) |
| `pnl_realized_unrealized.png` | `pnl.csv` | `gen_pnl_chart.py` |

Read this before regenerating. Running the NAV generator once against a plain NAV series produces a
**wrong** June bar (`+11.62%` instead of `+1.44%`), silently, with no error.

## Why two series

A **100,000 THB capital injection** landed in June. That is a *cash flow*, not a *return*, so the two
questions the charts answer need different bases:

| Chart | Series | Question it answers |
|---|---|---|
| `equity_curve.png` | actual NAV | What is the account actually worth? |
| `drawdown.png` | actual NAV | How far did the account fall from its own peak? |
| `monthly_returns.png` | TWR index | How did the *strategy* perform, with the injection neutralised? |

Mixing them is what goes wrong: on actual NAV, June reads **+11.62%**, which is mostly the operator
wiring in cash. On the time-weighted index it reads **+1.44%**, which is the investment return. The
monthly reviews for [June](../monthly/2026-06.md) and [July](../monthly/2026-07.md) both quote the
time-weighted figures, so `monthly_returns.png` must come from the TWR run.

## The two inputs

Both are `date,nav` CSVs of **60 points**, built from `db_csm_set.equity_curve` (60 rows,
2026-05-05 → 2026-07-31, one row per trading day at `00:00:00+00`) with two adjustments:

1. **A seed row `2026-05-04, 1000000.00`** is prepended — the live-test starting capital. Without it
   the drawdown is measured from the first *observed* close rather than from par, which understates
   the May trough (−4.22% instead of the correct **−4.60%**).
2. **`2026-06-04` is dropped.** That day's mark carries injection cash that had not yet been
   deployed, so it is a real account value but not a meaningful point on either series. The injection
   is treated as landing on **2026-06-05**, the restart baseline.

### `nav_actual.csv` — actual reported NAV

Seed + the 60 equity rows − `2026-06-04`. Nothing is rescaled. The visible ~8% step between
`2026-06-02` (1,014,485.27) and `2026-06-05` (1,095,967.18) **is** the injection.

### `nav_twr.csv` — time-weighted (flow-adjusted) index

Identical to `nav_actual.csv`, except every point from **2026-06-05 onward** is multiplied by

```
k = (NAV_2026-06-05 − 100,000) / NAV_2026-06-05
  = (1,095,967.18 − 100,000) / 1,095,967.18
  = 0.908756392
```

This chains the pre- and post-injection sub-periods so the flow contributes no return, while leaving
every *within-period* return untouched. The series starts at 1,000,000, so its value is directly
readable as an index: **1,017,778.24 at 2026-06-30 (+1.78%)** and **1,114,808.13 at 2026-07-31
(+11.48%)** — the inception-to-date time-weighted return.

## `pnl.csv` — realized vs unrealized P/L, and commission

Columns `date,realized_cum,unrealized,total_pl,commission_cum`, 60 rows, one per trading session.

- **`unrealized`** — read from each daily log's `Unrealized P/L` row (equivalently
  `Total Market Value − Total Cost Basis`). Moves every session; can round-trip to zero.
- **`realized_cum`** — a running sum of the per-rebalance realisations recorded in each
  rebalance-day daily log's Execution Summary. It only moves when a position is **closed**, so it is
  flat between rebalances by construction, and the chart draws it as a **step** for that reason.
- **`commission_cum`** — a running sum of the all-in fees on every fill. Only moves on a trading day.

The realisations to date:

| Date | Event | Realized | Cumulative |
|---|---|---:|---:|
| 2026-06-02 | Rebalance — NEX +6,591.99 · AGE −3,558.45 · JTS −7,385.41 | **−4,351.87** | −4,351.87 |
| 2026-07-01 | SELL MCOT (16,700 @ 5.15 vs 6.0374 basis) | **−14,964.06** | **−19,315.93** |

At 2026-07-31: realized **−19,315.93** · unrealized **+147,665.89** · total **+128,349.96** ·
commission **−3,052.51 THB**.

### The commission ledger

**Rate: 0.16799% all-in, both sides.** Commission 0.15% + SET trading 0.005% + TSD clearing 0.001% +
regulatory 0.001% = 0.157%, plus 7% VAT. Defined in
[`configs/live-settings.yaml`](../../../configs/live-settings.yaml) (`execution.fees`) and applied at
every fill. On a **buy** the fee is capitalised into `avg_cost`, so it shows up as unrealized drag; on
a **sell** it is deducted from proceeds, so it lands inside realized P/L. It is therefore never a
separate line in NAV — which is exactly why it needs its own column to be visible at all.

| Date | Event | Sell-side | Buy-side | Total | Source |
|---|---|---:|---:|---:|---|
| 2026-05-05 | Initial entry — 10 names | — | 1,611.15 | **1,611.15** | derived: cost basis × rate |
| 2026-06-02 | Rebalance 3-out / 3-in | 470.88 | 513.56 | **984.44** | fills table, [06-02 log](../daily/2026-06-02.md) |
| 2026-06-04 | MCOT tranche 1 | — | 80.96 | **80.96** | `live_portfolio.yaml` |
| 2026-06-05 | MCOT tranche 2 | — | 88.13 | **88.13** | `live_portfolio.yaml` |
| 2026-07-01 | MCOT → FORTH | 144.48 | 143.35 | **287.83** | `live_portfolio.yaml` |
| | **Total** | **615.36** | **2,437.15** | **3,052.51** | |

**Scale check:** 3,052.51 THB is **0.25% of NAV** over three months — but **15.8% of the realized
loss**, and rotation friction is the part that scales with turnover. The August 2-out/2-in will add
roughly 570 THB. Report both denominators; the NAV one alone makes it look free.

**Not plotted, deliberately.** At ~3k against a ±150k axis a fourth line renders as a smear on zero,
and a secondary axis would imply a comparability that isn't there. It appears in the chart title and
in the report tables instead.

### Reconciliation residual — known, constant, unexplained

`realized_cum + unrealized` overstates `NAV − capital base` by a **constant 1,609.61 THB** (0.13% of
NAV) from the 2026-06-02 rotation onward:

```
2026-07-31   total P/L  +128,349.96
             NAV − cap  +126,740.35   (1,226,740.35 − 1,100,000)
             residual      1,609.61
```

It is stable to the cent across every session since 2026-05-29, so it is a **fixed historical
amount** originating in the 2026-05-05 entry (before then it is larger and moving, because capital
was still being deployed).

**It is the entry commission, counted twice.** At the 2026-05-05 close,
`cost_basis + cash = 960,686.43 + 37,699.71 = 998,386.14`, i.e. **1,613.86 THB short of the
1,000,000 capital base** — and the commission implied inside that cost basis
(`960,686.43 × (1 − 1/1.0016799)`) is **1,611.15 THB**. The two agree to **2.71 THB**, which is the
expected per-symbol rounding across ten 4-decimal `avg_cost` values. So the entry fee was both
capitalised into `avg_cost` *and* deducted from cash, and the P/L decomposition consequently
overstates the NAV-based gain by that amount.

This is a **paper-ledger bookkeeping artifact, not a live-money discrepancy**, and it does not affect
NAV, which is measured directly as `MV + cash`. Left uncorrected on purpose: adjusting a historical
cost basis now would break the per-symbol `%U.PL` reproduction against the broker statement, which is
worth more than closing a 0.13% reconciliation gap. Recorded so the next reader does not re-derive it.

## Regenerating

```bash
cd strategies/csm-set
SKILLS=../../.claude/skills/csm-set-monthly-rebalance/scripts

# Run 1 — actual NAV. Keep equity_curve.png + drawdown.png (overwrites all three).
uv run python "$SKILLS/gen_monthly_charts.py" \
    --nav-csv docs/live-test/graphs/nav_actual.csv --out-dir docs/live-test/graphs

# Run 2 — TWR index into a scratch dir; copy back only monthly_returns.png.
uv run python "$SKILLS/gen_monthly_charts.py" \
    --nav-csv docs/live-test/graphs/nav_twr.csv --out-dir /tmp/twr
cp /tmp/twr/monthly_returns.png docs/live-test/graphs/monthly_returns.png

# P/L chart — independent, single run, writes only its own PNG.
uv run python "$SKILLS/gen_pnl_chart.py" \
    --pnl-csv docs/live-test/graphs/pnl.csv --out-dir docs/live-test/graphs
```

The generator writes all three PNGs on every run, which is why run 2 goes to a scratch directory —
letting it write into `graphs/` would overwrite the actual-NAV equity and drawdown charts with
index-based ones.

**Rebuild the CSVs first** whenever new months are added. `nav_actual.csv` is a straight dump of
`equity_curve` plus the seed row, minus `2026-06-04`; `nav_twr.csv` applies `k` from `2026-06-05`.
If another capital flow ever occurs, extend the TWR series with a second scale factor at that date —
do not re-derive `k` from the new NAV.

## Checks that must pass

| Check | Expected |
|---|---|
| July bar is identical on **both** bases | **+9.53%** — no flow in July, so `k` cancels. Disagreement means the CSVs are wrong |
| `equity_curve.png` last point | **1,226,740.35** @ 2026-07-31 |
| `drawdown.png` title | **−7.11%** (2026-07-30, against the 2026-07-22 peak of 1,262,400.35) |
| `monthly_returns.png` | May **+0.33%** · Jun **+1.44%** · Jul **+9.53%** |
| June bar vs the June review | must read **+1.44%**, not +11.62% |
| `pnl_realized_unrealized.png` | realized **−19,315.93** · unrealized **+147,665.89** · commission **−3,052.51** THB; the realized line is **flat except at 2026-06-02 and 2026-07-01** |
| P/L reconciliation | `realized_cum + unrealized − (NAV − capital)` = **1,609.61** and constant. A *changing* residual means a realisation was missed |
| `commission_cum` | rises **only on the 5 fill dates**; a rise on any other day means a non-trading day was credited with a fill |

## History

Regenerated **2026-08-01** for the July month-end. The previous set (2026-06-30) was produced by the
same two-run procedure, but the procedure itself was never written down — it had to be reconstructed
from the published figures before these charts could be reproduced. This file exists so that does not
happen again. The visible change from the June set is the drawdown title moving **−4.60% → −7.11%**:
July's 2026-07-30 trough is deeper than May's, so it becomes the since-inception worst.

**`pnl_realized_unrealized.png` is new on 2026-08-01** (operator request). Realized P/L had been
recorded only in prose, in the two rebalance-day daily logs, with the running total quoted by hand —
so "what has this strategy actually banked since inception?" could not be answered without reading
every rebalance log. It is now a committed series (`pnl.csv`) and a chart, and the daily, weekly and
monthly report skills all carry the cumulative figure.
