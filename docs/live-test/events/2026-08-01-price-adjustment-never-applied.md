# Event Report — Price adjustment has never been applied; the "dividends" store is split-adjusted only

**Date:** 2026-08-01 (found while regenerating the universe; affects all history to date)
**Category:** Data quality (silent — no error was ever raised)
**Severity:** Medium-High (every momentum factor the live test has computed is affected; no capital impact yet, and no trade has been shown to change)
**Status:** **RESOLVED 2026-08-09** — kwarg passed (PR #33), store regenerated, universe snapshots rebuilt, and the live container redeployed at 16:35 BKK; the 16:38 refresh wrote the first feature panel computed on total-return prices. Impact quantified (PR #34) and it is **smaller than feared**: the selection is **unchanged**. Two tails remain open — see Resolution. *(Was: Open — filed deliberately without a fix; operator decision 2026-08-01 was to **not** rewire before the 2026-08-03 ATO.)*

---

## Summary

`OHLCVLoader.fetch` resolves the requested price-adjustment mode, validates it, and then **throws it away**. The `adjustment` keyword is never passed to tvkit, so every fetch returns tvkit's default — **split-adjusted only**. The `--adjustment` flag on `fetch_history.py` / `build_universe.py` selects the *destination directory* and nothing else.

Consequently `data/raw/dividends/` does not contain dividend-adjusted prices. It contains exactly the same series as `data/raw/splits/`. Since the strategy reads the `dividends` store for everything, **every momentum factor computed in the live test to date — `mom_12_1`, `mom_6_1`, `mom_3_1`, `mom_1_0`, `sharpe_momentum`, `residual_momentum` — has been computed on split-adjusted-only prices while being documented as total-return.**

The in-code TODO defers this to "once tvkit>=0.11.0 ships". That reasoning is **stale**: the installed tvkit **0.6.0** already accepts the kwarg, and passing it demonstrably changes the data.

## How it was found

While regenerating the universe (2026-08-01) the stale `data/raw/splits/` store was rebuilt for completeness. The rebuilt store came back **byte-identical** to `data/raw/dividends/`, which should be impossible if the two adjustment modes were being applied. Reading the call site confirmed the kwarg is discarded; a direct two-mode tvkit fetch confirmed the kwarg works.

## Evidence

**1. The call site drops it** — `src/csm/data/loader.py:117-121`:

```python
effective: str = adjustment if adjustment is not None else self._settings.tvkit_adjustment
# TODO: pass adj_enum to client.get_historical_ohlcv() once tvkit>=0.11.0 ships.
_adj_enum: Adjustment = Adjustment(effective)
_ = _adj_enum  # referenced to satisfy linters until the tvkit kwarg is added
```

…and the actual call (`loader.py:131-135`) passes only `symbol`, `interval`, `bars_count`.

**2. The two stores are the same data** — 12 of 12 randomly sampled symbols compared with `DataFrame.equals`: **12 identical, 0 differing**.

**3. The kwarg works on the installed version** — direct fetch, `SET:PTT`, `bars_count=300`:

| Mode | last close | close 1y ago | oldest bar (2025-05-02) |
|---|---:|---:|---:|
| `Adjustment.SPLITS` | 38.50 | 31.25 | 31.25 |
| `Adjustment.DIVIDENDS` | 38.50 | **29.19659525** | **29.19659525** |

**203 of 300 bars differ.** `inspect.signature(OHLCV.get_historical_ohlcv)` on tvkit **0.6.0** lists `adjustment` as an accepted parameter, so the TODO's stated blocker does not apply.

**4. Magnitude on a single name** — SET:PTT 12-month momentum:

| | value |
|---|---:|
| As stored (split-adjusted only) | +23.20% |
| True dividend-adjusted | +31.86% |
| **Understated by** | **8.66 pp** |

## Root cause

1. **The kwarg was never wired.** The local `Adjustment` enum and the validation were added in anticipation of a tvkit API that had not shipped at the time; the call site was left unchanged and the TODO was never revisited after tvkit gained the parameter.
2. **The failure is silent by construction.** An unpassed keyword produces valid, plausible, internally consistent prices — just the wrong adjustment basis. Nothing raises, nothing logs, and the directory name (`dividends/`) actively asserts the opposite of what the files contain. There is no check anywhere that the two stores *should* differ.

## Impact

- **All live-test momentum factors are computed on split-adjusted-only prices.** The documented intent (`tvkit_adjustment` default `"dividends"` — "total-return backward adjustment (recommended for backtesting)") has never been realised.
- **The bias is systematic, not random.** Dividend adjustment lowers historical prices, so omitting it *understates* trailing returns for dividend-paying names in proportion to their yield. On a SET universe where mid-single-digit yields are common, this penalises high-yield names in the cross-section — a directional tilt in the ranking, not noise.
- **Scope is every ranking to date**, including the June 2 and July 1 rebalances and the 2026-08-03 plan.
- **No trade has been shown to change.** The impact has not been quantified at the portfolio level — doing so requires re-fetching both stores under the correct modes and re-running the rankings, which was deliberately not done before the 08-03 ATO (see Status).
- **No capital impact.** The live test is paper-only.

## Follow-up

1. **Pass the kwarg** — add `adjustment=_adj_enum` to `client.get_historical_ohlcv()` in `src/csm/data/loader.py` and delete the stale TODO. Small change; the enum is already resolved and validated one line above.
2. **Quantify before adopting.** Re-fetch both stores under their real modes, rebuild the universe and the 6-factor panel, and produce a **before/after ranking comparison** — including whether any past rebalance decision would have differed. Treat the switch as a methodology change with a dated cutover, not a silent data refresh.
3. **Decide on history.** The live test's banked signals and the July equity reconstruction were produced on the old basis. Decide explicitly whether to restate or to mark a cutover date and run forward from it.
4. **Add a guard.** A test asserting that a `splits` fetch and a `dividends` fetch of the same symbol differ would have caught this immediately and would catch any future regression. The current test suite cannot detect it because both modes are mocked identically.
5. **`quant-marketdata-engine` is the counter-example, and it settles the version question.** Its `ingest/tvkit_client.py:92` passes `adjustment=Adjustment.SPLITS` **explicitly and deliberately** — it stores raw/split-adjusted and applies dividend adjustment on read (ADR D2/D10). It does *not* carry the discarded-enum pattern. Two consequences: the kwarg is demonstrably usable in production today, so csm-set's omission is a plain bug rather than a version constraint; and the engine is the better model for how to hold this data. Separately worth checking there: `market_data.corporate_actions` is currently **empty (0 rows)**, so the engine's `/ohlcv/adjusted` adjust-on-read path has nothing to apply and returns split-adjusted prices under an "adjusted" name — a different route to the same class of silent mislabelling.

## Resolution — 2026-08-09

**Shipped.** Kwarg passed (`e04a292`, PR #33) with a regression test that records what the tvkit
client actually receives; `data/raw/dividends/` regenerated; universe snapshots rebuilt; the
container rebuilt and recreated at **16:35 BKK**, and its 16:38 refresh wrote the first
`features_latest.parquet` computed on total-return prices (204 symbols, all 7 factors).

**The impact is quantified, and it is smaller than this report feared** (`scripts/compare_adjustment_ranking.py`, PR #34).
Re-ranking the **2026-07-31** cross-section — 204 ranked, matching the actual rebalance's
denominator — from the **pre-rebalance** book, under both modes:

| Cut | Result |
|---|---|
| top-10 | **SELECTION IDENTICAL** |
| top-15 | **SELECTION IDENTICAL** |

- **PTTGC is evicted under both modes** (percentile 0.735 splits / 0.696 dividends) — the real
  2026-08-03 buffer eviction reproduces, and dividend adjustment ranks it *lower*, so the decision
  is better supported on corrected prices, not worse.
- Largest movers are high-payout names nowhere near the cut: **BTSGIF 0.108 → 0.520 (+0.412)**,
  NYT +0.162, ROJNA +0.108. Every held name moves ≤ 0.029.

⇒ **"No trade has been shown to change" is now a measurement rather than an absence of one**, for
the 2026-07-31 cross-section. The mechanism this report describes is real and large where it bites
— a 41-percentile-point move on an infrastructure fund is exactly the predicted direction and
magnitude — it simply did not reach the boundary that mattered on that date. **That is not a reason
the fix was optional:** the same mechanism will reach a cut eventually, and nothing would have said so.

⚠️ **What the re-rank does NOT cover, so it is not over-read:** the **per-holding EMA100 fast exit**
is not implemented in `src/csm/` (the in-code rule is index-level equity scaling; the monthly plans
applied it by hand), so **DELTA's eviction is unmodelled** and it reads "keep" in that output. The
63-day ADTV floor is likewise applied upstream during universe construction. The comparison answers
*"does the composite ranking pick different names?"* — not *"was the rebalance correct?"*

### Corrections this resolution makes to the report above

1. **"the installed tvkit **0.6.0**" is wrong** — 0.11.0 has been installed since `pyproject.toml`
   was pinned to `tvkit>=0.11.0` in `278de9c` on **2026-04-24, the same day the TODO was written**.
   Only the package's `__version__` attribute is stale at 0.6.0, which is what misled every reader
   including this report. **The TODO's stated blocker was void from the hour it was written.**
2. **"byte-identical" was imprecise, and the corrected form is stronger.** Bounded across **all 693**
   symbols rather than sampled: 663 byte-identical, 20 differing by a single `volume` cell (one
   2023-05-15 bar — an upstream revision), and 10 by ≤ **4.3e-06** relative — a rounding artifact
   four orders of magnitude below any dividend effect. **No symbol showed a dividend-shaped price
   difference**, which is the claim that actually matters.
3. **Follow-up 4 ("add a guard") landed in a better form than proposed.** Rather than asserting that
   two live fetches differ — which would need the network and would fail on a non-dividend-paying
   symbol — the fake client now **records the kwarg it receives**. Removing `adjustment=adj_enum`
   from the call site reds exactly those tests; the six older adjustment tests stay green, which is
   precisely why this survived three months.

### Still open (not closed by this work)

- **Follow-up 3, "decide on history", is untouched.** Every banked signal and the July equity
  reconstruction were produced on the old basis. There is now a **cutover at 2026-08-09** with
  no restatement, and no decision recorded either way.
- **`data/processed/universe_latest.parquet` has no producer in the codebase.** All three references
  (`api/scheduler/jobs.py:311`, `api/routers/data.py`, `api/routers/universe.py`) are **reads**;
  `build_universe.py` writes only dated snapshots under `data/universe/universe/`. The promotion is
  an undocumented manual step. Consequence today: the rebuilt **2026-07-31 snapshot carries 211
  symbols** while the live `universe_latest` still carries **210** — the difference is exactly
  **`SET:BANPU`**, which now passes the filters because the regenerated store finally has its bars.
  Promoting it is a live-universe change and was deliberately **not** done silently.
- **The `quant-marketdata-engine` counter-example in follow-up 5 still stands** and is unaffected by
  this fix: `market_data.corporate_actions` being empty means its `/ohlcv/adjusted` path can return
  split-adjusted prices under an "adjusted" name. csm-set runs `CSM_OHLCV_SOURCE=parquet`
  (pinned in `docker-compose.yml:61`), so it does not consume that path today — but the `db` default
  would.

## Related

- `docs/live-test/monthly/2026-07.md` — the 2026-08-01 amendment, and the **universe-truncation defect** found in the same session (live universe silently truncated to 136 of ~197 eligible symbols since 2026-05-04, corrected to 211).
- `docs/live-test/events/2026-06-30-rebalance-systematic-and-pipeline-gap.md` — the still-open ranking-pipeline gap (`daily_refresh` banks only 4 of the 6 factors); follow-up #1 there is a prerequisite for reproducing rankings without a manual re-fetch.
- `src/csm/data/loader.py` (call site), `src/csm/config/settings.py` (`tvkit_adjustment`), `scripts/fetch_history.py` / `scripts/build_universe.py` (`--adjustment`).
