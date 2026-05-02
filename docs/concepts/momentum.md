# Momentum Concept

This page explains the research concepts behind cross-sectional momentum as implemented in csm-set: the underlying theory, formation and skip periods, cross-sectional ranking methodology, SET-specific universe constraints, and pointers to the implementing source modules.

## Jegadeesh–Titman (1993) foundation

Cross-sectional momentum was first documented by Jegadeesh & Titman (1993) in *Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency*. The core finding: stocks that performed well over the past 3–12 months tend to continue outperforming over the next 3–12 months, and stocks that performed poorly tend to continue underperforming.

The strategy ranks stocks within a universe by their past return, buys the top-ranked names (winners), and sells or avoids the bottom-ranked names (losers). Unlike time-series momentum (which looks at a stock's own absolute performance trend), cross-sectional momentum exploits the *relative* performance spread between stocks.

### Formation and skip periods

A typical momentum signal is specified as a pair of integers: **F-SkM** (formation months, skip months). The three windows used in this implementation:

| Window | Formation | Skip | Description |
|--------|-----------|------|-------------|
| 12-1M | 11 months (t-12 to t-2) | 1 month (t-1) | Classic Jegadeesh–Titman; strongest academic evidence |
| 6-1M | 5 months (t-6 to t-2) | 1 month (t-1) | Medium-term; captures faster regime shifts |
| 3-1M | 2 months (t-3 to t-2) | 1 month (t-1) | Short-term; higher turnover but more responsive |

The most recent month (t-1) is always skipped to avoid short-term reversal — the tendency for the prior month's winners to mean-revert in the following month (Jegadeesh 1990). This skip-month convention is standard across the academic momentum literature.

### Cross-sectional ranking

Within each rebalance date, the momentum score for stock *i* is:

```
mom_i = (P_i,t-1 / P_i,t-F) - 1
```

where *P* is the adjusted close price, *F* is the formation window end, and *t-1* is the skip-month boundary.

Stocks are then ranked cross-sectionally at each date:

1. **Z-score normalisation** — within the current universe, each stock's momentum is standardised to mean 0, standard deviation 1.
2. **Quintile assignment** — stocks are sorted into 5 equal-weighted quintiles (Q1 = weakest momentum, Q5 = strongest).
3. **Long-only construction** — the strategy buys Q5 (top quintile) only. Long-short (Q5 − Q1) is computed for research purposes but not traded.

The z-scoring ensures comparability across time periods with different volatility regimes and prevents the signal from being dominated by a few extreme return observations.

---

## SET-specific universe constraints

The Thai equity market has structural features that constrain naive momentum implementations:

### Liquidity filter
Stocks must have **>= 100 million THB average daily value (ADV)** over the past 20 trading days. This eliminates ~60% of listed SET names and ensures the strategy can trade institutional-sized positions without excessive market impact.

### Listing age
Stocks must have been listed for **>= 12 months** to have a full formation window of historical data. Recent IPOs are excluded.

### Sector caps
No more than **30% of the portfolio** may come from a single SET sector. This prevents concentration in large sectors (Energy, Banking) and maintains the cross-sectional nature of the strategy.

### Regime filter
The strategy is disabled when the **SET Index closes below its 200-day simple moving average**. This is a basic trend filter — momentum strategies historically perform poorly in bear markets, and the regime filter reduces drawdown severity by moving to cash during extended downtrends.

### Universe rebalancing
The universe is reconstructed monthly (matching the rebalance frequency) to capture index additions/deletions, liquidity changes, and new listings.

---

## Implementation pointers

| Component | Module |
|-----------|--------|
| Momentum signal computation (12-1M, 6-1M, 3-1M) | `src/csm/features/momentum.py` — `MomentumFeatures` class |
| Risk-adjusted momentum (vol-scaled) | `src/csm/features/risk_adjusted.py` — `RiskAdjustedFeatures` class |
| Feature pipeline orchestration | `src/csm/features/pipeline.py` — `FeaturePipeline` class |
| Cross-sectional ranking (z-score + quintiles) | `src/csm/research/ranking.py` — `CrossSectionalRanker` class |
| IC analysis (rank IC, Pearson IC) | `src/csm/research/ic_analysis.py` — `ICAnalyzer` class |
| Walk-forward backtest engine | `src/csm/research/backtest.py` — `MomentumBacktest` class |
| Portfolio weight optimisation | `src/csm/portfolio/optimizer.py` — `WeightOptimizer` class |
| Universe construction (liquidity, listing age, sector caps) | `src/csm/data/universe.py` — `UniverseBuilder` class |
| Market regime detection (200-day SMA) | `src/csm/risk/regime.py` — `RegimeDetector` class |
| Strategy constants (lookbacks, thresholds) | `src/csm/config/constants.py` |

---

## Portfolio construction approaches

csm-set supports three portfolio weighting schemes, selectable via configuration:

### Equal weight (1/N)
Each stock in the top quintile receives an equal capital allocation (`w_i = 1 / N`). This is the simplest approach and the default. Equal weight avoids estimation error in expected returns and covariance, but does not account for differences in volatility across names.

### Volatility target
Position weights are scaled inversely to each stock's trailing 60-day realised volatility: `w_i ∝ (1 / σ_i) / Σ(1 / σ_j)`. The portfolio is then levered or de-levered to target a 15% annualised volatility. This produces more stable NAV paths but requires accurate volatility estimates.

### Minimum variance
Uses mean-variance optimisation with the objective `min w'Σw` subject to `Σw = 1` and `w_i >= 0`. The covariance matrix `Σ` is estimated from a trailing 252-day window with Ledoit-Wolf shrinkage to improve out-of-sample stability. Minimum variance tends to concentrate in low-volatility, low-correlation names and can underweight momentum itself if the signal and volatility are correlated.

### Constraints
All three schemes respect:
- **Long-only** — `w_i >= 0` (no shorting)
- **Max position weight** — `w_i <= 15%` (hard cap per stock)
- **Sector cap** — `Σ w_i_in_sector <= 30%`
- **Liquidity threshold** — positions are size-limited so that notional position size does not exceed 10% of the stock's 20-day ADV
- **Turnover limit** — maximum 100% one-way turnover per rebalance (constrains rebalancing to avoid excessive trading)

---

## Performance measurement

The strategy is evaluated along several dimensions:

### Signal quality metrics
- **Rank IC (Information Coefficient)**: Spearman rank correlation between momentum z-score at t and forward 1-month return. Positive and statistically significant IC (> 0.03 monthly) indicates the signal has predictive power.
- **Quintile spread**: The annualised return difference between Q5 (top) and Q1 (bottom). A monotonically increasing spread from Q1 to Q5 supports the signal.
- **IC decay**: How the IC changes as the forward horizon extends from 1M to 12M. Slow, smooth decay is preferable to a sharp drop-off.

### Portfolio metrics
- **CAGR**: Compound annual growth rate of the equity curve.
- **Volatility**: Annualised standard deviation of monthly returns.
- **Sharpe ratio**: `(CAGR - r_f) / σ` where `r_f` is the risk-free rate.
- **Sortino ratio**: Like Sharpe but uses downside deviation in the denominator.
- **Max drawdown**: Largest peak-to-trough decline in the equity curve.
- **Calmar ratio**: `CAGR / max_drawdown`.
- **Win rate**: Fraction of months with positive return.
- **Turnover**: Average one-way turnover per rebalance.

### Benchmark comparison
All metrics are computed against the SET Total Return Index (SET TRI) as the primary benchmark. The active return (strategy − benchmark) decomposition shows how much of the return comes from the momentum signal vs. broad market exposure.

---

## Backtest methodology

The walk-forward backtest in `MomentumBacktest` uses an expanding window:

1. **Initial training**: First 36 months of data used to calibrate the initial ranking and weighting parameters.
2. **Monthly step**: Each month, the universe is rebuilt (liquidity filter, listing age, sector caps), signals are recomputed with the trailing window, stocks are ranked and selected, weights are optimised, and the portfolio is rebalanced.
3. **Transaction costs**: A square-root impact model (`src/csm/execution/slippage.py`) estimates slippage as `σ * sqrt(Q / ADV)` where *Q* is the order size, *σ* is the stock's daily volatility, and *ADV* is average daily value. A minimum commission of 0.15% per trade is applied.
4. **Out-of-sample**: All parameters (lookback windows, thresholds, sector caps) are fixed before the backtest. No forward-looking information is used at any step.

---

## Practical considerations

### Data quality
Thai equity data from tvkit carries known issues: corporate actions (dividends, splits, rights offerings) may not be fully normalised in the raw feed. `csm.data.cleaner.PriceCleaner` applies outlier detection (5-sigma winsorisation per symbol), forward-fill for non-trading days, and dividend adjustment using total-return methodology.

### Survivorship bias
The backtest uses point-in-time universe snapshots (monthly reconstructions) and does NOT look ahead to filter stocks that later de-listed. Stocks that delist during the backtest period are held at their last traded price until the next monthly rebalance, when they fall out of the universe.

### Capacity
At 100M THB ADV minimum and 10% ADV position limit, the strategy's capacity depends on the number of qualifying stocks. With ~100–150 names in the SET meeting liquidity criteria and a top-quintile selection rate of ~20%, the strategy typically holds 20–30 positions. At a 10M THB notional, this is well within capacity for the Thai market.

### Look-ahead bias prevention
All signals are computed using data available *as of the rebalance date close*. The signal date is the last trading day of the month; execution is assumed at the next trading day's VWAP. No corporate action data beyond the rebalance date is used.

---

## References

- Jegadeesh, N. & Titman, S. (1993). *Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency.* Journal of Finance, 48(1), 65–91.
- Jegadeesh, N. (1990). *Evidence of Predictable Behavior of Security Returns.* Journal of Finance, 45(3), 881–898. — documents the short-term reversal effect that motivates the 1-month skip.
- Asness, C. S., Moskowitz, T. J. & Pedersen, L. H. (2013). *Value and Momentum Everywhere.* Journal of Finance, 68(3), 929–985. — shows momentum works across asset classes and geographies.
- Rouwenhorst, K. G. (1999). *Local Return Factors and Emerging Stock Markets.* Journal of Finance, 54(4), 1439–1464. — momentum evidence specifically in emerging markets.

## Cross-references

- [Architecture Overview](../architecture/overview.md) — data flow and layer map
- [Module Reference: Features](../reference/features/overview.md) — momentum signal API surface
- [Module Reference: Research](../reference/research/overview.md) — ranking and backtest API surface
- Phase 2 research notebooks: `notebooks/02_signal_research.ipynb` (signal analysis) and `notebooks/03_backtest_analysis.ipynb` (backtest results)
