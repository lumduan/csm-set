# Momentum Concept

This page explains the research concepts behind cross-sectional momentum as implemented in csm-set — formation periods, skip periods, ranking methodology, the Jegadeesh–Titman theoretical foundation, and the SET-specific universe constraints.

## Table of Contents

- [Cross-sectional momentum principles](#cross-sectional-momentum-principles)
- [Jegadeesh–Titman foundation](#jegadeesh-titman-foundation)
- [Formation and skip periods](#formation-and-skip-periods)
- [Cross-sectional ranking](#cross-sectional-ranking)
- [SET (Thai equities) universe constraints](#set-thai-equities-universe-constraints)
- [Implementation pointers](#implementation-pointers)
- [References](#references)

---

## Cross-sectional momentum principles

**Cross-sectional momentum** (also called *relative momentum* or *Jegadeesh–Titman momentum*) ranks stocks *within* a cross-section (e.g., all stocks in the SET on a given rebalance date) by their past return over a fixed lookback window. Stocks in the top quintile are bought; stocks in the bottom quintile are sold (or, in a long-only implementation, simply omitted).

This differs from **time-series momentum** (Moskowitz, Ooi & Pedersen 2012), which trades each asset based on its own past return regardless of how it compares to peers. Cross-sectional momentum captures the relative-strength effect: among all investable stocks, those that performed better over the lookback tend to continue outperforming in the near term.

The mechanics:

1. For each rebalance date *t* and each stock *i*, compute the log return from *t − 12 months* to *t − 1 month* (skipping the most recent month).
2. Within date *t*, compute the z-score of each stock's return relative to the cross-section.
3. Assign quintile labels (1 = weakest, 5 = strongest).
4. Construct a long-only portfolio of top-quintile stocks, equally weighted (or risk-weighted).

---

## Jegadeesh–Titman foundation

The strategy traces back to **Jegadeesh & Titman (1993)** , *Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency*. The authors found that buying past 6-month winners and selling past 6-month losers, held for 6 months, generated significant abnormal returns in the US market (1965–1989). The effect persisted after controlling for size, beta, and other known risk factors.

Key findings:

- The momentum effect is strongest at the 12-month horizon (formation period) with a 1-month skip
- Short-term reversal (1-month returns) is distinct from intermediate-term momentum
- The effect is not explained by systematic risk; it is a market anomaly

**Asness, Moskowitz & Pedersen (2013)** extended the finding globally, showing momentum works across eight asset classes and markets, including emerging markets. **Rouwenhorst (1999)** confirmed momentum in emerging markets specifically, finding similar magnitude and persistence as in developed markets.

csm-set implements this classic 12-1M variant alongside shorter lookbacks (6-1M, 3-1M) for comparison and robustness.

---

## Formation and skip periods

The momentum signal for a stock *i* on rebalance date *t* is computed as:

```
mom_12_1 = ln(close_{t − 1 month} / close_{t − 12 months})
```

The **skip period** (the most recent month, *t − 1 month* to *t*) is excluded. This is deliberate: Jegadeesh & Titman found that the most recent month exhibits *short-term reversal* (losers bounce, winners mean-revert), which dilutes the momentum signal. Skipping one month improves signal purity.

The four signals computed in `src/csm/features/momentum.py`:

| Signal | Lookback (trading days) | Skip (trading days) | Rationale |
|--------|-------------------------|---------------------|-----------|
| `mom_12_1` | 252 (≈12 months) | 21 (≈1 month) | Classic Jegadeesh–Titman |
| `mom_6_1` | 126 (≈6 months) | 21 (≈1 month) | Shorter-term variant |
| `mom_3_1` | 63 (≈3 months) | 21 (≈1 month) | Short-term variant |
| `mom_1_0` | 21 (≈1 month) | 0 | No-skip baseline (captures short-term reversal) |

The lookback windows use **trading-day offsets**, not calendar-day offsets. This correctly handles SET public holidays without needing a separate holiday calendar — if rebalance date *t* falls on a Thai holiday, the last available close before *t* is used.

---

## Cross-sectional ranking

Within each rebalance date, stocks are ranked by their momentum signal relative to all other stocks on that date.

### Ranking methodology (`src/csm/research/ranking.py`)

1. **Percentile rank:** For each signal column, compute `rank(method='average', pct=True)` within the date cross-section. Ties receive the average percentile. Result is in (0, 1]; higher = stronger momentum.
2. **Quintile assignment:** `pd.qcut` with 5 bins assigns labels 1–5 (1 = bottom quintile, weakest; 5 = top quintile, strongest). For small or highly tied cross-sections, a fallback with sparse labels (e.g., 1, 3, 5) is used. NaN if the symbol's signal is missing or binning fails entirely.
3. **Portfolio construction:** The top quintile (quintile 5) forms the long portfolio. In csm-set's default configuration, these stocks are equally weighted at rebalance.

### Information Coefficient (IC)

The rank IC is the cross-sectional Spearman correlation between the momentum signal at time *t* and the forward return over the holding period. A positive, statistically significant IC indicates predictive power. IC analysis is implemented in `src/csm/research/ic_analysis.py` and visualised in `notebooks/02_signal_research.ipynb`.

---

## SET (Thai equities) universe constraints

The SET is a concentrated emerging market (≈600–700 listed stocks, daily turnover concentrated in the top 100). csm-set applies market-specific filters to ensure the investable universe is realistic:

| Constraint | Threshold | Rationale |
|------------|-----------|-----------|
| Minimum ADV | ≥ 100M THB (≈$3M USD) | Ensures positions can be entered/exited without excessive market impact |
| Minimum listing | ≥ 12 months | Excludes IPOs without sufficient price history for signal computation |
| Sector cap | ≤ 40% of portfolio in any single sector | Prevents concentration in banking/energy (≈50–60% of SET market cap) |
| Regime filter | SET index above 200-day SMA | Reduces exposure during sustained bear markets |

The regime filter operates as a binary on/off switch: when the SET index closes below its 200-day simple moving average, the portfolio exits to cash (or risk-free equivalent). This is implemented in `src/csm/risk/regime.py` as `RegimeDetector.classify()`.

---

## Implementation pointers

| Concept | Code location |
|---------|---------------|
| Momentum signal computation | `src/csm/features/momentum.py` → `MomentumFeatures.compute()` |
| Risk-adjusted momentum | `src/csm/features/risk_adjusted.py` → `compute_risk_adjusted_momentum()` |
| Feature pipeline | `src/csm/features/pipeline.py` → `FeaturePipeline.compute_all()` |
| Cross-sectional ranking | `src/csm/research/ranking.py` → `CrossSectionalRanker.rank_all()` |
| IC analysis | `src/csm/research/ic_analysis.py` → `compute_ic()` |
| Walk-forward backtest | `src/csm/research/backtest.py` → `MomentumBacktest.run()` |
| Portfolio weight optimisation | `src/csm/portfolio/optimizer.py` → `optimize_weights()` |
| Regime detection | `src/csm/risk/regime.py` → `RegimeDetector.classify()` |
| Empirical validation | `notebooks/02_signal_research.ipynb` |

---

## References

- Jegadeesh, N. & Titman, S. (1993). *Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency.* Journal of Finance, 48(1), 65–91.
- Asness, C. S., Moskowitz, T. J. & Pedersen, L. H. (2013). *Value and Momentum Everywhere.* Journal of Finance, 68(3), 929–985.
- Rouwenhorst, K. G. (1999). *Local Return Factors and Turnover in Emerging Stock Markets.* Journal of Finance, 54(4), 1439–1464.
- Moskowitz, T. J., Ooi, Y. H. & Pedersen, L. H. (2012). *Time Series Momentum.* Journal of Financial Economics, 104(2), 228–250.
