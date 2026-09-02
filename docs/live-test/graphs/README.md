# Live-Test Charts — how these are generated

_🟢 **All four PNGs are back on ONE date.** The three **NAV** charts (`equity_curve`, `drawdown`,
`monthly_returns`) were regenerated at the **August month-end, 2026-08-31**, covering
2026-05-04 → 2026-08-31 (**80 NAV points**), from freshly rebuilt `nav_actual.csv` / `nav_twr.csv`.
The July-month-end split that this paragraph described from 2026-08-01 to 2026-08-31 is closed._
_`pnl.csv` was extended to **2026-08-31** on 2026-08-31 (adding the 08-31 row), so it now
runs **80 rows, 2026-05-05 → 2026-08-31**, and **`pnl_realized_unrealized.png` was regenerated from it
in the same session, so the CSV and the P/L PNG are in sync at 80 points**. Extending the CSV and
regenerating the chart in the same session is the established practice — it is what kept the
CSV-leads-the-PNG gap from reaching a commit on 2026-08-14, 2026-08-17, 2026-08-18, 2026-08-19,
2026-08-20, 2026-08-21, 2026-08-24, 2026-08-25, 2026-08-26, 2026-08-27, 2026-08-28 and 2026-08-31._
⚠️ **`pnl.csv` is built from the daily logs' figures, which come from `db_gateway.daily_performance`
and the YAML — the UN-restated basis. It therefore does NOT agree with `db_csm_set.equity_curve` on
historical rows after the 2026-08-24 KCE, 2026-08-25 INSET, 2026-08-26 MGC and 2026-08-28 FORTH
ex-dividend restatements, and that is correct rather than a discrepancy to reconcile. **FOUR names in
six sessions, and 6 of 10 held names now carry restated bars — a divergence here is the EXPECTED
state, not a defect.** 🟢 **2026-08-31 restated NOTHING, so no new divergence was added.** ➡️ **SUPERSEDED THE NEXT SESSION — the line below was true when written and is
NOT the current state.** ~~🟢 2026-08-27 restated NOTHING, so no new divergence was added and the
2026-08-26 rows of the two series still agree.~~ **FORTH's 2026-08-28 restatement moved every
`equity_curve` row from 2026-08-03 onward, including 2026-08-26 and 2026-08-27, so those rows no
longer agree either.** See the 2026-08-28, 2026-08-27, 2026-08-26, 2026-08-25 and 2026-08-24 History
entries._
`nav_actual.csv` / `nav_twr.csv` are **not** extended and still end 2026-07-31, so the three NAV
charts remain a July month-end artifact._

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

**Two capital injections have landed: 100,000 THB in June (2026-06-04) and 20,000 THB in August
(2026-08-03)**, taking the capital base 1,000,000 → 1,100,000 → **1,120,000**. Those are *cash
flows*, not *returns*, so the two questions the charts answer need different bases:

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
| 2026-07-01 | SELL MCOT (16,700 @ 5.15 vs 6.0374 basis) | **−14,964.06** | −19,315.93 |
| 2026-08-03 | Rebalance — SELL DELTA (300 @ 272.00 vs 319.5178) −14,392.42 · SELL PTTGC (3,000 @ 36.00 vs 41.0672) −15,383.03 | **−29,775.45** | **−49,091.38** |

At 2026-08-25 (the CSV's last row): realized **−49,091.38** · unrealized **+197,671.35** · total
**+148,579.97** · commission **−3,735.16 THB**. **Only the unrealized leg has moved since 2026-08-03** —
realized and commission have not changed since that rebalance, and will not until the September one.
(The pair read +129,844.35 / +80,752.97 at 2026-08-11, after falling on the 2026-08-10 MGC collapse
with no realisation involved, then recovered across 2026-08-13, 08-14, 08-17 and 08-18 before easing
−2,834.00 on 2026-08-19 and a further −35,094.00 on 2026-08-20 — the largest single-session fall
of the holding period — then recovering **+27,020.00 on 2026-08-21**, which returns total P/L above
the 200,000 line; none of it involved a realisation. **Read this line as
the CSV's last row, not as a live figure — the instrument is `pnl.csv` itself, and the owning record
is that day's log under `docs/live-test/daily/`.**)

&gt; The 2026-07-31 figures previously quoted here — realized −19,315.93 · unrealized +147,665.89 ·
&gt; total +128,349.96 · commission −3,052.51 — were **superseded by the 2026-08-03 rebalance**. They
&gt; remain correct *as of that date* and are the last row the PNG shows.

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
| 2026-08-03 | Rebalance 2-out / 2-in — DELTA 137.08 + PTTGC 181.43 sell; SMT 198.77 + MGC 165.37 buy | 318.51 | 364.14 | **682.65** | `live_portfolio.yaml`, [08-03 log](../daily/2026-08-03.md) |
| | **Total** | **933.87** | **2,801.29** | **3,735.16** | |

**Scale check:** 3,735.16 THB is **0.31% of NAV** over four months — but **7.6% of the realized
loss**, and rotation friction is the part that scales with turnover. Report both denominators; the NAV
one alone makes it look free.

&gt; ⚠️ **The estimate under-predicted, and the reason matters more than the gap.** This section
&gt; previously read *"The August 2-out/2-in will add roughly 570 THB."* The executed figure is
&gt; **682.65** — **19.8% higher** — because the fee is charged on *traded value*, and both buys filled
&gt; above their indicatives (SMT at 5.80 against a 4.78 indicative, +21.34%). A commission estimate
&gt; built from indicative prices inherits every bit of the execution slippage. Note also that the
&gt; **fee is the small half**: the same fills cost **−14,360.00 in slippage** against **−682.65** in
&gt; commission. Sizing friction off the commission line alone understates it by ~21×.

**Not plotted, deliberately.** At ~3k against a ±150k axis a fourth line renders as a smear on zero,
and a secondary axis would imply a comparability that isn't there. It appears in the chart title and
in the report tables instead.

### Reconciliation residual — known, constant, unexplained

`realized_cum + unrealized` overstates `NAV − capital base` by a **constant 1,610.27 THB** (0.13% of
NAV) from the 2026-08-03 rotation onward, and by **1,609.61** between 2026-05-29 and 2026-07-31:

```
2026-08-11   total P/L   +80,752.97
             NAV − cap   +79,142.70   (1,199,142.70 − 1,120,000)
             residual      1,610.27

2026-07-31   total P/L  +128,349.96
             NAV − cap  +126,740.35   (1,226,740.35 − 1,100,000)
             residual      1,609.61
```

It is stable to the cent across every session within each era, so it is a **fixed historical
amount** originating in the 2026-05-05 entry (before then it is larger and moving, because capital
was still being deployed).

**The +0.66 step at 2026-08-03 is expected, and is not a missed realisation.** It is the 4-decimal
`avg_cost` convention applied to the two entrants: SMT + MGC cost **217,124.14** all-in but are
carried at `shares × avg_cost` = **217,123.48**. A residual that *drifts* means a realisation was
missed; a **one-time step of exactly the rounding amount, then flat again**, is the convention doing
what it is documented to do. Expect a further sub-THB step at each future rotation.

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

&gt; 🔴 **That conditional has now FIRED — read it before the August regeneration.** A **second capital
&gt; injection of 20,000.00 THB landed 2026-08-03** (`starting_nav` rebased 1,100,000 → **1,120,000**).
&gt; The August month-end rebuild is therefore **the first that must chain two scale factors**, and
&gt; running the July procedure unchanged will silently book the injection as an August return — the
&gt; same class of error the top of this file warns about for June:
&gt;
&gt; ```
&gt; k₁ = (1,095,967.18 − 100,000) / 1,095,967.18 = 0.9087563918   applied from 2026-06-05
&gt; k₂ = (1,247,760.70 −  20,000) / 1,247,760.70 = 0.9839712855   applied from 2026-08-03
&gt; ```
&gt;
&gt; Apply `k₁ × k₂` from 2026-08-03 onward. **Do not re-derive either factor from the new NAV.**
&gt;
&gt; **One asymmetry versus June:** `2026-06-04` is dropped from `nav_actual.csv` because that day's mark
&gt; carried injection cash not yet deployed. **2026-08-03 must NOT be dropped** — the injection was
&gt; deployed in the same session (closing cash 3,027.70), so the mark is a real, fully-invested account
&gt; value. Drop it and the series loses a genuine point.

## Checks that must pass

| Check | Expected |
|---|---|
| July bar is identical on **both** bases | **+9.53%** — no flow in July, so `k` cancels. Disagreement means the CSVs are wrong |
| `equity_curve.png` last point | **1,317,530.70** @ 2026-08-31 *(was 1,226,740.35 @ 2026-07-31 until the 2026-08-31 rebuild)* |
| `drawdown.png` title | **−7.11%** (2026-07-30, against the 2026-07-22 peak of 1,262,400.35) — **unchanged by the August rebuild**; August's own worst was −4.73% |
| `monthly_returns.png` | May **+0.33%** · Jun **+1.44%** · Jul **+9.53%** · Aug **+5.68%** |
| **August bar is the TWR figure** | **+5.68%**, NOT the reported +7.40% and NOT the ex-injection +5.77%. Feeding `nav_actual.csv` instead reproduces the documented failure mode — **Jun +11.62%** and Aug +7.40% |
| June bar vs the June review | must read **+1.44%**, not +11.62% |
| `pnl_realized_unrealized.png` *(the 2026-08-31 PNG, through 08-31)* | realized **−49,091.38** · unrealized **+248,232.35** · commission **−3,735.16** THB; the realized line is **flat except at 2026-06-02, 2026-07-01 and 2026-08-03** — **three** steps. *(The superseded 2026-08-28 render showed −49,091.38 / +239,078.35 at 79 points; the 2026-08-27 one showed −49,091.38 / +245,069.35 at 78 points; the 2026-08-26 one showed −49,091.38 / +232,605.35 at 77 points; the 2026-08-25 one showed −49,091.38 / +197,671.35 at 76 points; the 2026-08-24 one showed −49,091.38 / +210,441.35 at 75 points; the 2026-08-21 one showed −49,091.38 / +249,619.35 at 74 points; the 2026-08-20 one showed −49,091.38 / +222,599.35 at 73 points; the 2026-08-19 one showed −49,091.38 / +257,693.35 at 72 points; the 2026-08-18 one showed −49,091.38 / +260,527.35 at 71 points; the 2026-08-17 one showed −49,091.38 / +231,713.35 at 70 points; the 2026-08-14 one −49,091.38 / +183,951.35 at 69 points; the 2026-08-12 one −49,091.38 / +129,844.35 at 67 points; the 2026-08-01 one −19,315.93 / +147,665.89 / −3,052.51 and only two steps.)* |
| `pnl.csv` last row *(the CSV and the P/L PNG are in sync — see the header)* | 2026-08-31: realized **−49,091.38** · unrealized **+248,232.35** · total **+199,140.97** · commission **3,735.16** THB; **80 rows**, matching `equity_curve`'s 80 **in row count only** — the values diverge historically after the KCE, INSET, MGC *and* FORTH restatements (see the header caveat) |
| The August regeneration *(**done** 2026-08-12, **superseded** by the 2026-08-14, 2026-08-17, 2026-08-18, 2026-08-19, 2026-08-20, 2026-08-21, 2026-08-24, 2026-08-25, 2026-08-26, 2026-08-27, 2026-08-28 and then the 2026-08-31 render)* | ✅ satisfied — the current PNG title reads `realized -49,091 · unrealized +248,232 · commission −3,735 THB`, the series ends 2026-08-31 at 80 points, and the realized line steps **three** times. Verified by eye against the rendered image, not only from the generator's stdout |
| Only ONE PNG may change on a P/L regeneration | ✅ `gen_pnl_chart.py:118` writes `pnl_realized_unrealized.png` and nothing else. Checksum the four PNGs before and after: the three NAV charts must be **byte-identical** and keep their 2026-08-01 mtimes. Verified 2026-08-14, 2026-08-17, 2026-08-18, 2026-08-19, 2026-08-20, 2026-08-21, 2026-08-24, 2026-08-25, 2026-08-26, 2026-08-27, 2026-08-28 and 2026-08-31 — only the P/L PNG's hash moved on all twelve |
| P/L reconciliation | `realized_cum + unrealized − (NAV − capital)` = **1,610.27** from 2026-08-03 (**1,609.61** for 2026-05-29 → 2026-07-31), and constant *within* each era. A *drifting* residual means a realisation was missed; the one-time **+0.66** step at the rotation is 4-dp `avg_cost` rounding — see above |
| `commission_cum` | rises **only on the 6 fill dates** (05-05, 06-02, 06-04, 06-05, 07-01, **08-03**); a rise on any other day means a non-trading day was credited with a fill |

## History

**`pnl.csv` extended through 2026-09-02** on 2026-09-02, appending the **2026-09-02** row — one row,
continuing the same-session practice for a **fourteenth** consecutive session. `realized_cum` and
`commission_cum` are unchanged (the September rebalance was a 0-out / 0-in, no-trade rotation), so
the whole movement is the unrealized leg (+204,583.35 → **+198,847.35**, a **−5,736.00** session),
and the reconciliation residual holds at **1,610.27**. **`pnl_realized_unrealized.png` was
regenerated in the same session**, so the two artifacts end together at **82 points**; the three NAV
charts were checksummed before and after and are byte-identical (`drawdown` eea580c3…,
`equity_curve` 25b0baf9…, `monthly_returns` aebd96bd…), with only the P/L PNG's hash moving
(67f656bb… → c11bb6b2…).

🔑 **`pnl.csv` and `equity_curve` now diverge on 2026-09-01, and the divergence is CORRECT.** The
vendor restated **FORTH's 2026-09-01 close, 15.50 → 15.40** (factor 0.9935483871). `equity_curve`
reprices `[entry_date, today]` against current history, so its 2026-09-01 row moved by exactly
`5,300 × −0.10 = −530.00` (1,273,881.70 → **1,273,351.70**). `pnl.csv` is built from the **daily
logs'** figures, so its 2026-09-01 row keeps the **as-published** unrealized of **+204,583.35**, and
`db_gateway.daily_performance` — being append-only — likewise still reads **1,273,881.70** for that
date. ⚠️ **Three series, two bases, and all three are right on their own terms.** This is the second
divergence of this kind the file records and it is **by design, not drift**: the rule is that
`pnl.csv` tracks what was published and `equity_curve` tracks what the panel currently says.

**`nav_actual.csv` and `nav_twr.csv` were not extended**, which is the ordinary mid-month state —
they are rebuilt from `equity_curve` **at month-end**, so the four PNGs sit on two dates as usual.
⚠️ **The next month-end rebuild will pick up the restated 2026-09-01 bar**, which is the intended
behaviour and is noted here so it is not re-diagnosed as a discrepancy then.

🟢 **The 2026-09-01 dual-bar corruption did not recur.** The panel is back to one row per trading
day (947 rows, all stamped 09:55), and the guards shipped that day logged nothing. See
`../events/2026-09-01-dual-bar-nav-corruption.md`.

**`pnl.csv` extended through 2026-09-01** on 2026-09-01, appending the **2026-09-01** row — one row,
continuing the same-session practice for a **thirteenth** consecutive session. `realized_cum` and
`commission_cum` are unchanged, and for a new reason: **the September rebalance was a 0-out / 0-in,
no-trade rotation** (`monthly/2026-08.md`), so there was no fill to record and the ledger holds at
**−49,091.38** / **−3,735.16**. The whole movement is the unrealized leg (+248,232.35 →
**+204,583.35**, a **−43,649.00** session — the third-largest single-session loss of the live test),
and the reconciliation residual holds at **1,610.27**. ⚠️ **The residual did NOT step at this
rotation** — the first rebalance not to move it — because no position entered at a fresh 4-dp
`avg_cost`. **`pnl_realized_unrealized.png` was regenerated from the extended CSV in the same
session**, so the two artifacts end together at **81 points**; the three NAV charts were checksummed
before and after and are byte-identical (`drawdown` eea580c3…, `equity_curve` 25b0baf9…,
`monthly_returns` aebd96bd…), with only the P/L PNG's hash moving (67c5af36… → 67f656bb…).

🔴 **`pnl.csv` IS THE ONLY CORRECT P/L SERIES FOR 2026-09-01, and that is not a coincidence — it is
because it is built from the daily log's figures rather than from `equity_curve`.** On 2026-09-01 the
price vendor began emitting a **second daily bar per session** and the NAV path priced the book off
the sparse one, writing **373,561.70** where the true NAV is **1,273,881.70** and **retroactively
overwriting the 2026-08-31 `equity_curve` row** (1,317,530.70 → **303,397.70**). ✅ **Both corrupt rows were
REPAIRED the same evening** — the defect was fixed, deployed and the production hook re-run, restoring
`equity_curve` 2026-08-31 to **1,317,530.70** and writing 2026-09-01 as **1,273,881.70**. So the two
series agree again on their latest rows, and `pnl.csv`'s 2026-09-01 unrealized of **+204,583.35**
reconciles against `equity_curve` exactly. ⚠️ **`nav_actual.csv` and `nav_twr.csv` were still NOT
extended today** — that is unchanged and deliberate, but the reason is now the ordinary one: they are
rebuilt from `equity_curve` **at month-end**, not daily. The four PNGs are consequently on two dates,
as they normally are mid-month. Full mechanism, footprint and resolution:
`../events/2026-09-01-dual-bar-nav-corruption.md`.

🟢 **NO corporate action occurred on 2026-09-01**, so no new divergence was added and the restatement
scope holds at 6 of 10 held names.

**AUGUST MONTH-END REGENERATION — 2026-08-31.** All three input CSVs rebuilt and all four PNGs
regenerated; the four artifacts are back on a single date for the first time since 2026-08-01.
`nav_actual.csv` **60 → 80 rows** (seed + every `equity_curve` row minus 2026-06-04, keeping
2026-08-03), `nav_twr.csv` likewise, `pnl.csv` at 80 rows.

🔴 **This was the first rebuild that had to chain TWO capital-flow scale factors**, and the fired
conditional above was executed as written: `k₁ = 0.9087563918` from 2026-06-05, `k₁ × k₂` with
`k₂ = 0.9839712855` from 2026-08-03. **Neither factor was re-derived** — which mattered more than
usual, because the 2026-08-03 `equity_curve` anchor `k₂` was originally derived from
(**1,247,760.70**) has since been restated to **1,240,806.78** by the FORTH ex-dividend adjustment.
Re-deriving would have moved a published historical figure to chase a number that itself moved.

**Regression, run before publishing:** all **60** previously-committed rows of both NAV CSVs are
**value-identical** (max |diff| 0.000000), and the three prior monthly bars are unchanged at
**May +0.33% · Jun +1.44% · Jul +9.53%**, with August landing at **+5.68%**. The same rebuild driven
from `nav_actual.csv` instead yields **Jun +11.62%** — the exact documented failure mode — which is
the control proving the TWR series is the one that reached the chart. All four PNGs were checked
against the rendered images, not only the generators' stdout. ✅ Only `monthly_returns.png` came from
the scratch-directory TWR run; `equity_curve.png` and `drawdown.png` came from the actual-NAV run, as
the recipe requires.

⚠️ **Why no historical row moved despite four restatements.** The reconstruction reprices the
*current* book back over `[entry_date, today]`, and `entry_date` is **2026-08-03** — so every
`equity_curve` row from 08-03 forward moved, and **nothing before it did.** June and July bars were
therefore never at risk this month. **That will not hold at the next rotation**, which resets
`entry_date` and widens the rewritable window.

**`pnl.csv` extended through 2026-08-31** on 2026-08-31, appending the **2026-08-31** row — one row,
continuing the same-session practice for a **twelfth** consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+239,078.35 → **+248,232.35**, a **+9,154.00** session), and the reconciliation
residual holds at **1,610.27**.
**`pnl_realized_unrealized.png` was regenerated from the extended CSV in the same session**, so the
two artifacts end together at **80 points**; the three NAV charts were checksummed before and after
and are byte-identical with their 2026-08-01 mtimes intact.

🟢 **NO corporate action occurred on 2026-08-31, so no new divergence was added** and the restatement
scope holds at 6 of 10 held names. ⚠️ **This is expected to be the LAST row written under the current
book.** 2026-08-31 is the last trading day of August; the September rotation executes at the
**2026-09-01 ATO**, which rewrites positions, cash and cost basis — and the reconciliation residual
will **step** at that rotation as it did on 2026-08-03 (1,609.61 → 1,610.27), because new positions
enter at 4-dp `avg_cost` rounding. **Take the new residual from the execution log, not from this
file's current value.**

**`pnl.csv` extended through 2026-08-28** on 2026-08-28, appending the **2026-08-28** row — one row,
continuing the same-session practice for an **eleventh** consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+245,069.35 → **+239,078.35**, a **−5,991.00** session), and the reconciliation
residual holds at **1,610.27**.
**`pnl_realized_unrealized.png` was regenerated from the extended CSV in the same session**, so the
two artifacts end together at **79 points**; the three NAV charts were checksummed before and after
and are byte-identical with their 2026-08-01 mtimes intact.

🔴 **FORTH went ex-dividend on 2026-08-28 (factor 0.9907975776, 0.15 THB/share, 795.00 THB on 5,300
shares), so a new divergence WAS added — and it retroactively changes the previous entry's claim.**
The 2026-08-27 entry below recorded that no corporate action occurred and that the two series' rows
still agreed; **that was true when written and is no longer true.** The back-adjustment is
multiplicative and applies to FORTH's whole history, so **every `equity_curve` row from 2026-08-03
onward moved** — the 2026-08-27 row from 1,314,367.70 to 1,313,572.700371, and the 2026-08-03 anchor
from 1,241,674.938372 to 1,240,806.779239 (a shift of **−868.16**, which is exactly
`5,300 × 17.80 × (1 − factor)` computed forward from the factor, not fitted to the observation).
**`pnl.csv` did not move and must not** — it is the un-restated basis by construction, and the
divergence is the expected state. **Scope is now 6 of 10 held names carrying restated bars.**

**`pnl.csv` extended through 2026-08-27** on 2026-08-27, appending the **2026-08-27** row — one row,
continuing the same-session practice for a **tenth** consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+232,605.35 → **+245,069.35**, a **+12,464.00** session), and the reconciliation
residual holds at **1,610.27**.
**`pnl_realized_unrealized.png` was regenerated from the extended CSV in the same session**, so the
two artifacts end together at **78 points**; the three NAV charts were checksummed before and after
and are byte-identical with their 2026-08-01 mtimes intact.

🟢 **NO corporate action occurred on 2026-08-27, ending a three-session streak — and that absence is
what makes this entry worth recording.** The prior three entries each documented a restatement
(KCE 08-24, INSET 08-25, MGC 08-26). Today **all ten held-name 2026-08-26 closes matched the values
the 2026-08-26 log published**, the `equity_curve` history did not move, and the 2026-08-03 anchor
held. ⇒ **No new divergence was added between `pnl.csv` and `equity_curve`**, and the two series
**agree on the 2026-08-26 row** (both 1,301,903.70).

⚠️ **The clean session is a CONTROL, and it decomposed a defect the three dirty sessions could only
describe.** `db_gateway.daily_performance.daily_return` reproduced **to seven decimal places** as
`(NAV change) ÷ TODAY's NAV` — the original denominator defect **alone**, with no restatement term
superimposed. ⇒ The field has **two independent defects**, only one of which is always present: a
**fixable one-line denominator bug** (understates gains by ~0.01pp on a clean session) and a
**restatement sensitivity** of unpredictable sign and up to 17× the magnitude, which only the
restate-vs-cutover decision can remove. The 2026-08-26 entry's conclusion that the field "cannot be
corrected by a constant" is **refined, not overturned** — the constant part can be, the other part
cannot. **This is a better-specified defect report than any of the three restated sessions could
produce, and it exists only because a clean session followed them.**

**`pnl.csv` extended through 2026-08-26** on 2026-08-26, appending the **2026-08-26** row — one row,
continuing the same-session practice for a **ninth** consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+197,671.35 → **+232,605.35**, a **+34,934.00** session — the largest single-day
gain of the holding period), and the reconciliation residual holds at **1,610.27**.
**`pnl_realized_unrealized.png` was regenerated from the extended CSV in the same session**, so the
two artifacts end together at **77 points**; the three NAV charts were checksummed before and after
and are byte-identical with their 2026-08-01 mtimes intact.

🔴 **A THIRD corporate action landed on the third consecutive session — MGC went ex-dividend on
2026-08-26** (0.24/share, **2,208.00 THB** on 9,200 shares, factor **0.97018634**), after KCE on
08-24 and INSET on 08-25. **5 of 10 held names now carry restated bars.** What this entry adds over
the two before it is that **the mechanism is now characterised, not just observed**: the vendor's
backward adjustment is **multiplicative**, so the THB shift it induces on any `equity_curve` row is
`shares × that date's as-printed price × (1 − factor)` — **NOT the flat dividend amount**. Verified
to 4 dp on three independent points (MGC 08-03 predicted 2,825.1424 vs observed −2,825.142440;
MGC 08-25 predicted 2,207.9996 vs observed −2,208.00; and, retroactively, INSET 08-03 predicted
2,004.1486 vs the **−2,004.15** the 2026-08-25 entry recorded as an unexplained figure sitting
alongside a 2,100.00 dividend).

⇒ **Two practical consequences for anyone reading these artifacts.** (1) The divergence between
`pnl.csv` and `db_csm_set.equity_curve` is **not** a fixed per-name offset — it varies by date with
the price on that date, so it cannot be reconciled by subtracting a dividend. (2) The
multiplicative-invariance argument quoted in the 2026-08-24 and 2026-08-25 entries holds only for
**single-date, single-name ratios** (per-symbol `U.PL %`, EMA100 distance — both re-verified
2026-08-26). It does **NOT** hold for **cross-date portfolio ratios**: `combined_drawdown` moved
from −4.4611% to −4.4527% on 2026-08-26 **with no new trough**, purely because its peak and trough
were rescaled by different THB amounts (2,427.43 vs 2,208.00). `pnl.csv` is on the un-restated
basis throughout and is internally consistent; **prefer it and the daily logs over `equity_curve`
for any historical P/L question.**

**`pnl.csv` extended through 2026-08-25** on 2026-08-25, appending the **2026-08-25** row — one row,
continuing the same-session practice for an **eighth** consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+210,441.35 → **+197,671.35**, a **−12,770.00** session), and the reconciliation
residual holds at **1,610.27**.
**`pnl_realized_unrealized.png` was regenerated from the extended CSV in the same session**, so the
two artifacts end together at **76 points**; the three NAV charts were checksummed before and after
and are byte-identical with their 2026-08-01 mtimes intact.

🔴 **A SECOND corporate action landed one session after the first, and that is what makes this entry
worth reading rather than skimming: INSET went ex-dividend on 2026-08-25** (0.05/share, **2,100.00
THB** on 42,000 shares), restating INSET's whole price history by factor **0.98962656** and rewriting
`db_csm_set.equity_curve` again — the 2026-08-24 row moved to 1,277,639.70 against
`daily_performance`'s 1,279,739.70, a gap of exactly the dividend. **The prior entry framed the KCE
restatement as "a caveat no prior entry has needed"; two names in two sessions makes it the standing
condition of this file, not a caveat.** **4 of the 10 held names now carry restated bars** (EPG,
GUNKUL, KCE, INSET). `pnl.csv` is built from `db_gateway.daily_performance`, which is
append-one-row-per-day and was **not** rewritten, so this file and the daily logs remain on the
un-restated basis and are internally consistent. ⚠️ **Do not "reconcile" `pnl.csv` against
`equity_curve`'s historical values.** The row counts still match (76); the values do not, on every
date either name was held. Owning record: `docs/live-test/daily/2026-08-25.md` Risk Note 13.

**`pnl.csv` extended through 2026-08-24** on 2026-08-25, appending the **2026-08-24** row — one row,
continuing the same-session practice for a seventh consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+249,619.35 → **+210,441.35**, a **−39,178.00** session — the largest loss of the
holding period), and the reconciliation residual holds at **1,610.27**.
**`pnl_realized_unrealized.png` was regenerated from the extended CSV in the same session**, so the
two artifacts end together at **75 points**; the three NAV charts were checksummed before and after
and are byte-identical with their 2026-08-01 mtimes intact.

🔴 **This session carries a caveat no prior entry has needed: KCE went ex-dividend on 2026-08-24**
(0.60/share, **1,560.00 THB** on 2,600 shares), and the backward price adjustment restated KCE's whole
history by factor **0.98914027**. That propagated through the equity reconstruction and **rewrote all
75 rows of `db_csm_set.equity_curve`**. **`db_gateway.daily_performance` was NOT rewritten**, and
**`pnl.csv` is built from the latter**, so this file and the daily logs remain on the un-restated
basis and are internally consistent. ⚠️ **Do not "reconcile" `pnl.csv` against `equity_curve`'s
historical values — they are deliberately on different bases now.** The row counts still match (75);
the values do not, on every date KCE was held. Owning record:
`docs/live-test/daily/2026-08-24.md` Risk Note 13.
➡️ **The "no prior entry has needed" framing was SUPERSEDED THE NEXT SESSION — see the 2026-08-25
entry above**, where INSET did the same thing and turned a one-off into the standing condition.

**`pnl.csv` extended through 2026-08-21** on 2026-08-21, appending the **2026-08-21** row — one row,
continuing the same-session practice for a sixth consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+222,599.35 → **+249,619.35**, a **+27,020.00** session), and the reconciliation
residual holds at **1,610.27**. **`pnl_realized_unrealized.png` was regenerated from the extended CSV
in the same session**, so the two artifacts end together at **74 points**; the three NAV charts were
checksummed before and after and are byte-identical with their 2026-08-01 mtimes intact.

**The session recovered 77.0% of the record loss of 2026-08-20**, on breadth of **4 up / 1 down /
5 flat** — five unchanged closes, the most of the holding period, each one independently re-fetched
because a half-unchanged book is the shape a partially-failed refresh produces. Total P/L returns to
**+200,527.97**, back above the 200,000 line for the second time; unrealized rises to
**+249,619.35**, leaving NAV **0.82% off its 2026-08-18 peak**. **INSET and SMT both set fresh
live-test highs**, and **SMT's 5.80 is the new maximum close of its entire 600-bar window** — which
**withdraws** the characterisation of that level as a bound made in the 2026-08-20 daily log.
➡️ **SUPERSEDED THE NEXT SESSION — see the 2026-08-24 entry above**, which gave back −39,178.00 and
in which SMT surrendered the 5.80 breakout recorded here after exactly one session.
⚠️ **The 2026-08-20 entry below is accurate as of that date and was superseded the next session** —
read it as history, not as the current figure. Owning record: `docs/live-test/daily/2026-08-21.md`.

**`pnl.csv` extended through 2026-08-20** on 2026-08-20, appending the **2026-08-20** row — one row,
continuing the same-session practice for a fifth consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+257,693.35 → **+222,599.35**, a **−35,094.00** session), and the reconciliation
residual holds at **1,610.27**. **`pnl_realized_unrealized.png` was regenerated from the extended CSV
in the same session**, so the two artifacts end together at **73 points**; the three NAV charts were
checksummed before and after and are byte-identical with their 2026-08-01 mtimes intact.

**This is the largest single-session fall of the holding period on both the THB and the percentage
measure**, and it came with **every one of the ten positions down** — the first 0/10/0 session since
the 2026-08-03 rotation, and the exact mirror of 2026-08-13's 10/0/0. Total P/L falls to
**+173,507.97**, back below the 200,000 line it first cleared on 2026-08-18 and held for two sessions;
unrealized falls to **+222,599.35**, leaving NAV **2.85% off its 2026-08-18 peak**. **The SET rose
+0.01% on the same day**, so the fall was the book's rather than the market's. ➡️ **SUPERSEDED THE
NEXT SESSION — see the 2026-08-21 entry above**, which recovered +27,020.00 of this fall. ⚠️ **The
2026-08-19 entry below is accurate as of that date and was superseded the next session** — read it
as history, not as the current figure. Owning record: `docs/live-test/daily/2026-08-20.md`.

**`pnl.csv` extended through 2026-08-19** on 2026-08-19, appending the **2026-08-19** row — one row,
continuing the same-session practice for a fourth consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+260,527.35 → **+257,693.35**, a **−2,834.00** session), and the reconciliation
residual holds at **1,610.27**. **`pnl_realized_unrealized.png` was regenerated from the extended CSV
in the same session**, so the two artifacts end together at **72 points**; the three NAV charts were
checksummed before and after and are byte-identical with their 2026-08-01 mtimes intact.

**This is the first down session since the two consecutive all-time highs**, and it is a shallow one:
total P/L eases to **+208,601.97**, still above the 200,000 line first cleared on 2026-08-18 and still
the second-highest close of the live test, leaving NAV **0.21% off its 2026-08-18 peak**. Unrealized
eases to **+257,693.35**. ➡️ **SUPERSEDED THE NEXT SESSION — see the 2026-08-20 entry above**, which
records a −35,094.00 fall to +173,507.97. ⚠️ **The 2026-08-18 entry below is likewise accurate as of
that date only.** Owning record: `docs/live-test/daily/2026-08-19.md`.

**`pnl.csv` extended through 2026-08-18** on 2026-08-18, appending the **2026-08-18** row — one row,
continuing the same-session practice for a third consecutive session. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+231,713.35 → **+260,527.35**, a **+28,814.00** session), and the reconciliation
residual holds at **1,610.27**. **`pnl_realized_unrealized.png` was regenerated from the extended CSV
in the same session**, so the two artifacts end together at **71 points**; the three NAV charts were
checksummed before and after and are byte-identical with their 2026-08-01 mtimes intact.

**Total P/L closed above 200,000 THB for the first time**, at **+211,435.97** — a second consecutive
live-test high, now **47,426.01** above the 2026-07-22 pre-rotation peak of +164,009.96. Unrealized
also set a second consecutive high at **+260,527.35**. NAV made a new all-time high on both the raw
and ex-injection lines for a second session. Owning record: `docs/live-test/daily/2026-08-18.md`.

**`pnl.csv` extended through 2026-08-17** on 2026-08-17, appending the **2026-08-17** row — one row,
not two, because the 2026-08-14 session closed its backlog rather than carrying it. `realized_cum` and
`commission_cum` are unchanged (**no trade since the 2026-08-03 rotation**), so the whole movement is
the unrealized leg (+183,951.35 → **+231,713.35**, a **+47,762.00** session), and the reconciliation
residual holds at **1,610.27**. **`pnl_realized_unrealized.png` was regenerated from the extended CSV
in the same session**, so the two artifacts end together at **70 points**; the three NAV charts were
checksummed before and after and are byte-identical with their 2026-08-01 mtimes intact.

**This is the session that closed the divergence described in the 2026-08-14 entry below.** Total P/L
reached **+182,621.97**, clearing the 2026-07-22 peak of +164,009.96 by **18,612.01** — so **total P/L
is now at a live-test high**, and the "total P/L is NOT at a high" finding recorded below is **correct
as of 2026-08-14 and superseded on 2026-08-17**. NAV also made a new all-time high on both the raw and
ex-injection lines. Owning record: `docs/live-test/daily/2026-08-17.md`.

**`pnl.csv` extended through 2026-08-14** on 2026-08-14, appending the **2026-08-13** and
**2026-08-14** rows in one step. Two rows rather than one because the 08-13 row was flagged as
outstanding in that day's log and not appended at the time, so it compounded by exactly one session —
the reason the daily log's Risk Note 9 escalated it from "ordinary maintenance" to a named follow-up.
No 2026-08-12 row exists and none should: the SET was closed (H.M. Queen Sirikit The Queen Mother's
Birthday). `realized_cum` and `commission_cum` are unchanged across both rows — **no trade has
occurred since the 2026-08-03 rotation** — so the entire movement is the unrealized leg
(+129,844.35 → +176,806.35 → +183,951.35), and the reconciliation residual holds at **1,610.27** on
both. **`pnl_realized_unrealized.png` was regenerated from the extended CSV in the same session**, so
the two artifacts end together at 69 points and the CSV-leads-the-PNG gap never reached a commit.
Only that one PNG changed — the three NAV charts were checksummed before and after and are
byte-identical, still carrying their 2026-08-01 mtimes.

**The regenerated chart shows a divergence worth reading deliberately, because it is the whole reason
these series are plotted separately.** ➡️ **SUPERSEDED ON 2026-08-17 — total P/L reached +182,621.97,
a live-test high (see the top of this section). The divergence described below was real on 2026-08-14
and is now closed.** **Unrealized P/L set a live-test high at +183,951.35**, edging
past the 2026-07-22 peak of +183,325.89 by **625.46** — while **total P/L is NOT at a high**: it reads
**+134,859.97** against 2026-07-22's **+164,009.96**, sitting **29,149.99** below it. The gap is almost
entirely the 2026-08-03 realisation of **−29,775.45**, and the two reconcile exactly:
`29,775.45 − 29,149.99 = 625.46`, the unrealized excess. **A chart of NAV alone would show neither
fact**; a chart of unrealized alone would report a record while concealing that a rotation was banked
at a loss in between.

**`pnl_realized_unrealized.png` regenerated 2026-08-12**, off-cycle rather than at a month-end,
because `pnl.csv` had been extended through 2026-08-11 and the PNG was the last artifact still
publishing the pre-rebalance pair. It is the **first time the four PNGs sit on two different dates** —
the P/L chart is current to 2026-08-11, the three NAV charts remain the 2026-08-01 July month-end set,
because `nav_actual.csv` / `nav_twr.csv` were not extended. Read the two groups separately until the
August month-end brings the NAV charts forward. The visible change from the 2026-08-01 render is the
realized line gaining its **third** step at 2026-08-03 (−19,315.93 → −49,091.38) and the unrealized
line extending through the 2026-07-22 peak, the 2026-08-10 MGC collapse and the 08-11 close.

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
