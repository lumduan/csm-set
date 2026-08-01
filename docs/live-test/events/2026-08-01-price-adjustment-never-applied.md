# Event Report — Price adjustment has never been applied; the "dividends" store is split-adjusted only

**Date:** 2026-08-01 (found while regenerating the universe; affects all history to date)
**Category:** Data quality (silent — no error was ever raised)
**Severity:** Medium-High (every momentum factor the live test has computed is affected; no capital impact yet, and no trade has been shown to change)
**Status:** Open — filed deliberately without a fix; operator decision 2026-08-01 was to **not** rewire before the 2026-08-03 ATO

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

## Related

- `docs/live-test/monthly/2026-07.md` — the 2026-08-01 amendment, and the **universe-truncation defect** found in the same session (live universe silently truncated to 136 of ~197 eligible symbols since 2026-05-04, corrected to 211).
- `docs/live-test/events/2026-06-30-rebalance-systematic-and-pipeline-gap.md` — the still-open ranking-pipeline gap (`daily_refresh` banks only 4 of the 6 factors); follow-up #1 there is a prerequisite for reproducing rankings without a manual re-fetch.
- `src/csm/data/loader.py` (call site), `src/csm/config/settings.py` (`tvkit_adjustment`), `scripts/fetch_history.py` / `scripts/build_universe.py` (`--adjustment`).
