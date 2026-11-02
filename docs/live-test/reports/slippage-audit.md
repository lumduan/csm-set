# Slippage Audit — Phase C exit criterion C.2

**Date:** 2026-11-02, the evening of the November rotation
**Required by:** `docs/plans/live-test/PLAN.md` §Phase C, C.2 *Slippage Audit*:
- compare `ExecutionSimulator`'s estimated slippage against actual SET bid-ask spread data for the stocks the strategy traded;
- document any calibration gap;
- collect Level 1 quotes at rebalance times if possible.

Ticket: [[TK-0571]].
**Status:** 🟡 **FILED, with one question for the operator (§5): how were the orders placed?** Most recorded fills do not match the opening-auction price that the registered fill rule names. Nothing in the configuration or the code was changed.
**Reproduce:** [`slippage-audit/`](slippage-audit/) holds the fill dataset (`fills.json`, every row transcribed from its rotation day's published log), the two scripts and `results.json`. Every number below is taken from `results.json` (§8).

---

## Summary

1. **The engine's slippage model has never run in the live test, and it ignores its configuration when it does.** `ExecutionSimulator.__init__` constructs `SqrtImpactSlippageModel()` with the default config, whatever `ExecutionConfig.slippage_model` says ([[TK-0569]]). That default is **10 bps half-spread + 10 × √participation**. On the 28 live fills it estimates **2,590.70 THB, 10.45 bps** of notional.
2. **The measured spreads are 2–4 times the model's half-spread.** On the six traded names with captured depth, the time-weighted median half-spread is **18.2–38.0 bps**, and the spread is exactly one tick **93–100%** of the time. On the SET, a name's minimum crossing cost is set by its tick size against its price, which the model's single 10 bps does not see.
3. **Against the decision price (the evaluation close), the fills cost +16,809.00 THB (+70.6 bps) in total, and one trade is all of it.**
   - SMT on 2026-08-03 cost +2,133.9 bps: the stock opened 4.8 against a 4.78 close and was bought at 5.80.
   - Without that fill, the other 25 fills with a decision price *gained* 3,999.00 THB (−17.7 bps).
   - The median fill costs **0.0 bps** against each of the three references.
4. 🔴 **Most recorded fills do not match the opening auction.**
   - The reported price equals that day's open in **7 of 28** fills and that day's close in **9 of 28**. All 28 sit inside the day's high–low range.
   - On 2026-11-02 only **1 of 12** equals the open, and the fills beat the open by **+18,681.00 THB** in total.
   - Where the captured trade tape is at least 99.98% complete (2026-10-01), CNT's 18,200-share buy does not appear in the opening auction (500 + 100 shares printed), and only 3,000 shares traded at 3.34 all day.
5. **Twenty-eight fills cannot calibrate `impact_coef`.** Participation never exceeded 2.40% of 63-day ADTV, so the impact term was never larger than 1.55 bps. The half-spread can be set from the quotes now (§7).

---

## 1. What was measured

| Source | What it gives | Coverage |
|---|---|---|
| Rotation-day daily logs | every fill's side, shares and reported price; the decision price (the prior evaluation close) and the day's close, as published | 28 fills, 2026-06-02 → 2026-11-02. The 2026-05-05 entry is excluded because its log records commission-inclusive averages, not execution prices. The two MCOT tranches (2026-06-04, 06-05) have no decision price: they were deferred fills of a 2026-05-29 decision |
| tvkit daily bars | each fill day's open, high, low, close and volume; 63-day ADTV before the trade | every fill. The published closes equal the vendor's on all 28 |
| Order-book capture (`quant-orderbook-engine`, compacted store, read-only) | quotes (`SP_DepthV1`) and trades (`SP_MarketTickerV1`) | depth for KCE, IRPC, GUNKUL, HANA and SPRC on 2026-10-30 and DELTA on 2026-08-03; trades for DELTA (2026-08-03), MGC and CNT (2026-10-01). **The 2026-11-02 data is compacted overnight**, so today's auction prints are a follow-up (§6) |

**Three reference prices, each answering a different question.** Every figure below is signed so that **positive = a cost to the book**.

- **Decision price** (the evaluation close the plan was priced on): the cost of executing the plan at all, including the overnight gap.
- **Open** (the day's opening-auction price): what the registered fill rule — *one ATO order per side* (registration §4, D3) — would have produced.
- **Close** (the day's close): the daily logs' mark-to-close figure.

---

## 2. The model

```text
slippage_bps = half_spread_bps + impact_coef × √(notional / ADTV63)
             = 10 + 10 × √participation          (the config ExecutionSimulator actually builds)
```

| | Value |
|---|---:|
| Fills | 28 |
| Notional | 2,480,130.00 THB |
| Highest participation | 2.40% of 63-day ADTV (MCOT, 2026-07-01) |
| Model estimate | **2,590.70 THB (10.45 bps)** |
| Fees paid (0.16799% schedule) | 4,166.39 THB |

The impact term never exceeded 1.55 bps (10 × √0.024), so on this book the model is almost entirely its flat 10 bps.

---

## 3. What the spread actually is

Quoted spreads from the captured depth, continuous-trading phases only (feed phase bytes 2 and 4, `Open1` and `Open2`, per `docs/reference/streaming-pro-set-wire-formats.md` §1.2.1), uncrossed books, time-weighted:

| Day | Name | Tick | Median mid | Spread (time-weighted median) | Half-spread | One tick, at the median mid | Spread = one tick |
|---|---|---:|---:|---:|---:|---:|---:|
| 2026-10-30 | IRPC | 0.02 | 2.63 | 76.0 bps | **38.0 bps** | 76.0 bps | 99.58% |
| 2026-10-30 | SPRC | 0.10 | 13.50 | 73.8 bps | **36.9 bps** | 74.1 bps | 96.03% |
| 2026-10-30 | HANA | 0.25 | 44.375 | 56.3 bps | **28.2 bps** | 56.3 bps | 97.49% |
| 2026-10-30 | GUNKUL | 0.02 | 4.67 | 42.6 bps | **21.3 bps** | 42.8 bps | 99.09% |
| 2026-10-30 | KCE | 0.25 | 66.375 | 37.5 bps | **18.8 bps** | 37.7 bps | 93.19% |
| 2026-08-03 | DELTA | 1.00 | 274.5 | 36.4 bps | **18.2 bps** | 36.4 bps | 98.89% |

- **On these names the book is one tick wide almost all the time**, so the spread in basis points is the tick divided by the price. A 2–5 THB name pays 40–80 bps to cross; a 40–70 THB name, 35–60 bps.
- **The model's 10 bps half-spread is 1.8 to 3.8 times too small** for every name measured. A trade that crosses the spread in continuous trading pays at least half a tick.
- ⚠️ **An opening-auction order crosses no spread.** It trades at the single auction price. Under the registered fill rule the half-spread term should not apply at all, and the relevant cost is the auction price against the decision price.

---

## 4. The fills

**By rotation** (positive = cost; bps of the fills' notional):

| Rotation | Fills | Notional | vs decision | vs open | vs close | Model | Fees | = open | = close |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2026-06-02 | 6 | 586,012.00 | +6,105.00 (+104.2) | +6,190.00 (+105.6) | +1,652.00 (+28.2) | 623.74 | 984.44 | 2 | 1 |
| 2026-06-04 | 1 | 48,195.00 | — | 0.00 (0.0) | −1,215.00 (−252.1) | 51.65 | 80.96 | 1 | 0 |
| 2026-06-05 | 1 | 52,460.00 | — | 0.00 (0.0) | +1,290.00 (+245.9) | 56.63 | 88.13 | 1 | 0 |
| 2026-07-01 | 2 | 171,335.00 | +755.00 (+44.1) | +530.00 (+30.9) | +1,510.00 (+88.1) | 186.71 | 287.83 | 1 | 0 |
| 2026-08-03 | 4 | 406,360.00 | +25,778.00 (+634.4) | +23,250.00 (+572.2) | +14,360.00 (+353.4) | 416.87 | 682.65 | 1 | 1 |
| 2026-10-01 | 2 | 120,128.00 | +728.00 (+60.6) | −824.00 (−68.6) | +2,184.00 (+181.8) | 126.33 | 201.81 | 0 | 1 |
| 2026-11-02 | 12 | 1,095,640.00 | −16,557.00 (−151.1) | −18,681.00 (−170.5) | −3,317.00 (−30.3) | 1,128.77 | 1,840.57 | 1 | 6 |
| **All** | **28** | **2,480,130.00** | **+16,809.00 (+70.6)** | **+10,465.00 (+42.2)** | **+16,464.00 (+66.4)** | **2,590.70** | **4,166.39** | **7** | **9** |

*The vs-decision column covers 26 fills; the two deferred MCOT tranches have no decision price.*

**Per fill:**

| Date | Side | Name | Shares | Fill | Decision | Open | Close | vs decision | vs open | vs close | Model |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2026-06-02 | SELL | NEX | 99,000 | 1.08 | 1.08 | 1.08 | 1.10 | 0.0 | 0.0 | +181.8 | 10.6 |
| 2026-06-02 | SELL | AGE | 80,600 | 1.22 | 1.22 | 1.22 | 1.24 | 0.0 | 0.0 | +161.3 | 11.3 |
| 2026-06-02 | SELL | JTS | 1,900 | 39.50 | 39.75 | 40.00 | 39.00 | +62.9 | +125.0 | −128.2 | 10.3 |
| 2026-06-02 | BUY | KCE | 2,600 | 39.00 | 37.50 | 38.50 | 39.75 | +400.0 | +129.9 | −188.7 | 10.1 |
| 2026-06-02 | BUY | EASTW | 24,000 | 4.26 | 4.26 | 4.24 | 4.22 | 0.0 | +47.2 | +94.8 | 11.0 |
| 2026-06-02 | BUY | EPG | 17,300 | 5.90 | 5.80 | 5.70 | 5.90 | +172.4 | +350.9 | 0.0 | 10.5 |
| 2026-06-04 | BUY | MCOT | 8,100 | 5.95 | — | 5.95 | 6.10 | — | 0.0 | −245.9 | 10.7 |
| 2026-06-05 | BUY | MCOT | 8,600 | 6.10 | — | 6.10 | 5.95 | — | 0.0 | +252.1 | 10.8 |
| 2026-07-01 | SELL | MCOT | 16,700 | 5.15 | 5.10 | 5.15 | 5.05 | −98.0 | 0.0 | −198.0 | 11.5 |
| 2026-07-01 | BUY | FORTH | 5,300 | 16.10 | 15.80 | 16.00 | 15.50 | +189.9 | +62.5 | +387.1 | 10.2 |
| 2026-08-03 | SELL | DELTA | 300 | 272.00 | 278.00 | 279.00 | 272.00 | +215.8 | +250.9 | 0.0 | 10.0 |
| 2026-08-03 | SELL | PTTGC | 3,000 | 36.00 | 36.75 | 36.25 | 36.50 | +204.1 | +69.0 | +137.0 | 10.1 |
| 2026-08-03 | BUY | SMT | 20,400 | 5.80 | 4.78 | 4.80 | 5.35 | +2,133.9 | +2,083.3 | +841.1 | 10.4 |
| 2026-08-03 | BUY | MGC | 9,200 | 10.70 | 10.60 | 10.70 | 10.30 | +94.3 | 0.0 | +388.3 | 10.5 |
| 2026-10-01 | SELL | MGC | 9,200 | 6.45 | 6.45 | 6.40 | 6.45 | 0.0 | −78.1 | 0.0 | 10.3 |
| 2026-10-01 | BUY | CNT | 18,200 | 3.34 | 3.30 | 3.36 | 3.22 | +121.2 | −59.5 | +372.7 | 10.7 |
| 2026-11-02 | SELL | EASTW | 24,000 | 4.20 | 4.16 | 4.16 | 4.16 | −96.2 | −96.2 | −96.2 | 10.7 |
| 2026-11-02 | SELL | FORTH | 5,300 | 13.20 | 13.30 | 13.30 | 13.20 | +75.2 | +75.2 | 0.0 | 10.3 |
| 2026-11-02 | SELL | INSET | 33,600 | 4.42 | 4.30 | 4.28 | 4.38 | −279.1 | −327.1 | −91.3 | 10.6 |
| 2026-11-02 | SELL | KCE | 2,100 | 72.00 | 68.75 | 68.75 | 71.50 | −472.7 | −472.7 | −69.9 | 10.1 |
| 2026-11-02 | SELL | SMT | 16,400 | 7.40 | 7.20 | 7.25 | 7.40 | −277.8 | −206.9 | 0.0 | 10.3 |
| 2026-11-02 | SELL | IRPC | 45,300 | 2.62 | 2.60 | 2.56 | 2.62 | −76.9 | −234.4 | 0.0 | 10.2 |
| 2026-11-02 | SELL | GUNKUL | 24,700 | 4.56 | 4.64 | 4.62 | 4.56 | +172.4 | +129.9 | 0.0 | 10.2 |
| 2026-11-02 | SELL | HANA | 2,400 | 46.00 | 45.25 | 45.00 | 46.00 | −165.7 | −222.2 | 0.0 | 10.1 |
| 2026-11-02 | SELL | EPG | 13,900 | 6.10 | 6.00 | 6.10 | 6.05 | −166.7 | 0.0 | −82.6 | 10.3 |
| 2026-11-02 | SELL | CNT | 14,600 | 3.00 | 3.00 | 2.94 | 3.02 | 0.0 | −204.1 | +66.2 | 10.7 |
| 2026-11-02 | BUY | SPRC | 1,200 | 13.80 | 13.60 | 13.50 | 13.80 | +147.1 | +222.2 | 0.0 | 10.1 |
| 2026-11-02 | BUY | SSP | 2,200 | 7.70 | 7.75 | 7.75 | 7.50 | −64.5 | −64.5 | +266.7 | 10.2 |

*bps, positive = cost.*

**Reading.**

- **The typical fill cost nothing.** The median is 0.0 bps against every reference, and the per-fill spread runs from −472.7 to +2,133.9 bps. That range is market movement, not execution cost: each fill's distance from any one reference is mostly where the price went that day.
- **The aggregate is one trade.** SMT on 2026-08-03 (+2,133.9 bps against its decision price) was an overnight repricing that no execution model covers. The other 25 fills with a decision price netted a gain.
- **The model's 10 bps is neither confirmed nor refuted by the fills.** It is far below the noise, and twenty-eight fills cannot separate a 10 bps cost from zero.

---

## 5. The tape check — and the question for the operator

The registered fill rule is **one ATO order per side** (registration §4, D3). An ATO order executes at the opening auction's single price, so an ATO fill should equal that day's open. **It does in 7 of 28 fills.**

| | Open | Close | Recorded fill |
|---|--:|--:|---|
| Fills equal to the open | 7 | | NEX, AGE (06-02); MCOT ×3; MGC (08-03); EPG (11-02) |
| Fills equal to the close | | 9 | EPG (06-02); DELTA (08-03); MGC (10-01); FORTH, SMT, IRPC, GUNKUL, HANA, SPRC (11-02) |
| Neither | | | 12 fills |
| Inside the day's high–low range | all 28 | | |

**Three fills checked against the captured trade tape** (`SP_MarketTickerV1`). The tape's first print equals the vendor's open and its last print the vendor's close in each case:

| Day | Fill | Tape completeness vs vendor volume | Opening auction | Traded at the recorded price, whole day |
|---|---|---:|---|---:|
| 2026-08-03 | SELL DELTA 300 @ 272.00 | 96.07% | 279.00 × 345,300 | 3,550,100 shares (272.00 is the close) |
| 2026-10-01 | SELL MGC 9,200 @ 6.45 | 99.98% | 6.40 × 17,800 | 243,900 shares (6.45 is the close) |
| 2026-10-01 | BUY CNT 18,200 @ 3.34 | 99.99% | 3.36 × 500 | **3,000 shares** |

- **CNT:** the opening auction printed 500 shares, so an 18,200-share ATO buy is not in it. All day, only 3,000 shares traded at 3.34. The recorded 3.34 is therefore not a single execution price for 18,200 shares. It may be an average of several executions.
- **MGC and DELTA:** an ATO sell would have filled at the open (6.40 and 279.00). The recorded prices are the closes.
- **On 2026-11-02**, 11 of 12 recorded prices differ from the open, and 6 equal the close. Today's tape is compacted overnight (§6).

🔴 **The question: how were the orders placed?** (ATO, ATC, or limit orders during the session; and do the broker confirmations show the same prices?)

- **This is not a finding of error.** Every recorded price lies inside that day's high–low range, and the 2026-10-01 and 2026-11-02 quantities match their plans.
- **It decides three things:**
  - which reference price is the right one for this audit;
  - whether the recorded prices are the executed ones, which the realized P/L and NAV are built on;
  - whether execution followed the registered fill rule. Registration §6 #7 counts trades the rules do not produce, not execution timing. How a fill-rule difference is treated is the operator's call.
- **Until it is answered, the books keep the reported prices.**

---

## 6. What this audit cannot show

- **Twenty-eight fills, seven rotations.** Participation never exceeded 2.40%, so the impact term was never tested. Most of the per-fill dispersion is the day's price movement.
- **Quotes for only six of the traded names.** The depth capture held 99 SET equity series on 2026-10-01 and 2026-10-30; the other traded names have trades in the capture but no quotes, and their spreads are not measured here.
- **The 2026-11-02 tape is not yet compacted.** Its opening-auction prints, and the volume traded at each reported price, will be added once the store has them (from 2026-11-03) — in the next daily log, and here as an addendum.
- **The 2026-05-05 entry is not covered**: its log records commission-inclusive averages, not execution prices.
- **There is still no fill series outside the daily logs** ([[TK-0565]]): `trade_history` holds no rows, so this audit was built by transcription, and the checker re-reads every row from its log.

---

## 7. Calibration findings and recommendations (none applied)

1. **`half_spread_bps`: replace the flat 10 bps with half a tick at the trade price** (one tick wide 93–100% of the time on every measured name), floored by a measured median where depth exists. For the names measured that is 18.2–38.0 bps.
2. **Separate auction executions from continuous ones.** At an opening auction the half-spread does not apply; the cost to model is the auction price against the decision price, an overnight-gap risk.
3. **`impact_coef`: not calibrated, deliberately.** Twenty-eight fills with participation under 2.40% cannot estimate it ([[TK-0571]]: *"do not fit the model to twelve points and call it calibrated"*).
4. **Wire the configuration through** ([[TK-0569]]): until `ExecutionSimulator` passes `ExecutionConfig.slippage_model` to the model, any calibration above changes nothing.
5. **Record fills where code can read them** ([[TK-0565]]), with the order type and time from the broker confirmation, so that the reference-price question of §5 is answered by the record.
6. **No change inside the scored window.** `PLAN.md:294` and the registration both require it.

---

## 8. Reproduce

Run from a directory with no `.env`, with `CSM_PUBLIC_MODE=true CSM_OHLCV_SOURCE=parquet CSM_DB_WRITE_ENABLED=false`:

    uv run --project <repo> python docs/live-test/reports/slippage-audit/fetch_ohlc.py       # tvkit daily OHLCV → ohlc_tvkit.csv (gitignored)
    uv run --project <repo> python docs/live-test/reports/slippage-audit/slippage_audit.py   # → results.json

`slippage_audit.py` reads `fills.json`, `ohlc_tvkit.csv` and the order-book capture's compacted store (`COLD_SP` overrides its path), and writes `results.json`. Every table above is taken from that file.
