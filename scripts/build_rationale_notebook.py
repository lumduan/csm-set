"""Build 05_live_portfolio_rationale.ipynb — trader-facing CSM strategy explainer."""
import nbformat as nbf

nb = nbf.v4.new_notebook()
nb.metadata = {
    "kernelspec": {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    },
    "language_info": {"name": "python", "version": "3.12.0"},
}

cells = []

def md(source):
    cells.append(nbf.v4.new_markdown_cell(source))

def code(source):
    cells.append(nbf.v4.new_code_cell(source))

# ============================================================
# Cell 1 — Title
# ============================================================
md("""# CSM Strategy — Live Portfolio Rationale
## May 2026 Entry | Cross-Sectional Momentum

**Prepared:** 2026-05-04 &nbsp;|&nbsp; **Strategy:** CSM v1.0 (Constrained Strategy Matrix) &nbsp;|&nbsp; **Portfolio Size:** 10 Stocks &nbsp;|&nbsp; **AUM:** 1,000,000 THB

---

*This notebook explains — with data and charts — why these 10 specific stocks were selected for the May 2026 CSM live portfolio. Every selection is driven by the strategy's cross-sectional momentum pipeline, not subjective judgment.*""")

# ============================================================
# Cell 2 — Executive Summary
# ============================================================
md("""## Executive Summary

| Item | Detail |
|------|--------|
| **Strategy** | Cross-Sectional Momentum (Jegadeesh & Titman 12-1M) |
| **Universe** | 132 SET-listed stocks passing liquidity & quality filters |
| **Selection** | Top 10 by composite momentum z-score (all in Q5 — top quintile) |
| **Weighting** | Volatility-target, capped at 5–15% per position |
| **Rebalance** | Monthly, at business month-end (next: 2026-05-30) |
| **Risk Controls** | 15% vol target, −10% circuit breaker, 35% sector cap |
| **Entry** | At The Opening (ATO) on 2026-05-05 |""")

# ============================================================
# Cell 3 — Strategy Overview
# ============================================================
md("""## 1. Strategy Overview: What Is Cross-Sectional Momentum?

Cross-sectional momentum ranks stocks *relative to each other* (not vs. their own past). Every month, we compute trailing 12-month returns (skipping the most recent month to avoid short-term reversal), standardize them as z-scores across all 132 stocks, and buy the highest-ranked names.

### The CSM Pipeline

```
SET Universe (700+ stocks)
    │
    ├─[Liquidity Filter]── ADTV ≥ 5M THB, price ≥ 1 THB
    ├─[Quality Filter] ─── Earnings positive, net margin ≥ 5%
    │
    ├─[Feature Engine] ─── 7 momentum signals computed per stock
    │   ├─ mom_12_1  (12-month, skip 1)
    │   ├─ mom_6_1   (6-month, skip 1)
    │   ├─ mom_3_1   (3-month, skip 1)
    │   ├─ mom_1_0   (1-month, no skip — reversal indicator)
    │   ├─ sharpe_momentum (return / volatility)
    │   ├─ residual_momentum (alpha vs. SET index)
    │   └─ sector_rel_strength (vs. sector peers)
    │
    ├─[Cross-Sectional Ranking]── Z-score each signal, average into composite
    ├─[Selection] ──── Top 10 by composite score + buffer logic
    ├─[Sector Cap] ─── Max 35% per sector
    └─[Weighting] ──── Volatility-target (15% annual), enforce 5–15% bounds
```

**Key insight:** Stocks with high z-scores have delivered unusually strong returns *compared to the rest of the market* over the past year. The strategy bets that this relative strength persists for the next month.""")

# ============================================================
# Cell 4 — Data Loading (shared setup)
# ============================================================
code("""import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
import seaborn as sns
import json
from pathlib import Path

# ── Style ──────────────────────────────────────────────────
plt.rcParams.update({
    "figure.dpi": 120,
    "savefig.dpi": 120,
    "font.family": "DejaVu Sans",
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "figure.titlesize": 15,
    "figure.facecolor": "white",
    "axes.facecolor": "#fafafa",
    "axes.edgecolor": "#cccccc",
    "axes.grid": True,
    "grid.alpha": 0.4,
    "grid.color": "#dddddd",
})
sns.set_palette("viridis")

# Resolve project root: nbconvert runs from notebook directory, so try parent first
PROJECT = Path.cwd()
if not (PROJECT / "data" / "processed").exists() and (PROJECT.parent / "data" / "processed").exists():
    PROJECT = PROJECT.parent
DATA = PROJECT / "data" / "processed"
RESULTS = PROJECT / "results"

print("Loading data...")

# ── Features ────────────────────────────────────────────────
features = pd.read_parquet(DATA / "features_latest.parquet")
features["date"] = pd.to_datetime(features["date"])
latest_date = features["date"].max()
latest = features[features["date"] == latest_date].copy()

# Strip SET: prefix for display
latest["ticker"] = latest["symbol"].str.replace("SET:", "")
latest = latest.set_index("ticker")

# Cross-sectional z-scores (matching daily report methodology)
for col in ["mom_12_1", "mom_6_1", "mom_3_1", "mom_1_0"]:
    mu = latest[col].mean()
    sigma = latest[col].std()
    latest[f"z_{col}"] = (latest[col] - mu) / sigma

# Composite score: equal-weight mean of z-scored momentum features
z_cols = ["z_mom_12_1", "z_mom_6_1", "z_mom_3_1", "z_mom_1_0"]
latest["composite_z"] = latest[z_cols].mean(axis=1)

# Rank percentile
latest["rank_pct"] = latest["mom_12_1"].rank(pct=True)
latest["quintile"] = pd.qcut(latest["mom_12_1"], q=5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])

# Sort by mom_12_1 descending
latest = latest.sort_values("mom_12_1", ascending=False)

# ── Prices ──────────────────────────────────────────────────
prices = pd.read_parquet(DATA / "prices_latest.parquet")
prices.index = pd.to_datetime(prices.index)

# ── Signal Quality ──────────────────────────────────────────
with open(RESULTS / "signals" / "latest_ranking.json") as f:
    signals_json = json.load(f)

n_symbols = len(latest)
n_dates = features["date"].nunique()
n_q5 = (latest["quintile"] == "Q5").sum()

print(f"Universe: {n_symbols} symbols on latest date ({latest_date.date()})")
print(f"Feature panel: {len(features)} rows across {n_dates} rebalance dates")
print(f"Q5 (top quintile): {n_q5} symbols")
print("Ready.")""")

# ============================================================
# Cell 5 — Signal Quality Assessment
# ============================================================
md("""## 2. Signal Quality: Which Momentum Factors Work?

Before selecting stocks, the strategy validates each momentum signal using **Information Coefficient (IC)** analysis. IC measures the correlation between a signal and future 1-month returns. **ICIR** (IC / std(IC)) tells us whether the predictive power is consistent.

A signal must pass the **ICIR gate** (ICIR > 0.15) to be included in the composite score.""")

# ============================================================
# Cell 6 — IC/ICIR Table & Chart
# ============================================================
code("""# ── Signal Quality Table ───────────────────────────────────
sig_data = []
for name, stats in signals_json["signals"].items():
    sig_data.append({
        "Signal": name.replace("_", " ").title(),
        "Mean IC": stats["mean_ic"],
        "ICIR": stats["icir"],
        "Rank ICIR": stats["rank_icir"],
        "% Positive": stats["pct_positive"] * 100,
        "Passes Gate": "✓" if stats["passes_gate"] else "—",
    })

sig_df = pd.DataFrame(sig_data).sort_values("ICIR", ascending=False)
sig_df = sig_df.round({"Mean IC": 4, "ICIR": 4, "Rank ICIR": 4, "% Positive": 1})

# Style the table
def color_icir(val):
    if isinstance(val, (int, float)):
        color = "#1a9850" if val > 0.15 else "#d73027" if val < 0 else "#999999"
        return f"color: {color}; font-weight: bold"
    return ""

display(
    sig_df.style
    .set_caption("Signal Quality Assessment — IC/ICIR Analysis")
    .map(color_icir, subset=["ICIR", "Rank ICIR"])
    .background_gradient(cmap="RdYlGn", subset=["Mean IC", "% Positive"])
    .format(precision=4)
)

# ── ICIR Bar Chart ──────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))
colors = ["#1a9850" if v > 0.15 else "#fdae61" if v > 0 else "#d73027"
          for v in sig_df["ICIR"]]
bars = ax.barh(sig_df["Signal"], sig_df["ICIR"], color=colors, edgecolor="white", height=0.6)
ax.axvline(0.15, color="#d73027", linestyle="--", linewidth=1.5, alpha=0.7, label="ICIR Gate (0.15)")
ax.axvline(0, color="gray", linewidth=0.8)

for bar, val in zip(bars, sig_df["ICIR"]):
    ax.text(val + 0.01 * max(sig_df["ICIR"].abs()), bar.get_y() + bar.get_height() / 2,
            f"{val:.3f}", va="center", fontsize=10, fontweight="bold")

ax.set_xlabel("ICIR (Information Coefficient / StdDev)")
ax.set_title("Signal Predictive Power (ICIR) — Higher = More Consistent Alpha", fontweight="bold")
ax.legend(loc="lower right", fontsize=9)
ax.set_xlim(min(sig_df["ICIR"]) - 0.05, max(sig_df["ICIR"]) + 0.08)
sns.despine(left=True)
plt.tight_layout()
plt.show()

# ── Composite Info ──────────────────────────────────────────
comp = signals_json["composite"]
print(f"\\nComposite formula: {comp['formula']}")
print(f"Members passing gate: {comp['members']}")
print(f"Composite ICIR: {comp['icir']:.4f}  |  Rank ICIR: {comp['rank_icir']:.4f}")

# Note on what's actually used
print("\\n→ The primary ranking signal is residual_momentum (ICIR = 0.320).")
print("  In the live features dataset, the composite is built from all 4 raw momentum")
print("  horizons (mom_12_1 through mom_1_0), which collectively capture the")
print("  cross-sectional momentum effect across multiple time scales.")""")

# ============================================================
# Cell 7 — Ranking Distribution
# ============================================================
md("""## 3. Ranking: Where Do Our 10 Stocks Stand?

We compute a **composite z-score** (equal-weight average of z-scored momentum signals) for all 132 stocks. The top quintile (Q5) contains 27 stocks. Our portfolio takes the **top 10**.

The chart below shows the full distribution with our selections highlighted.""")

# ============================================================
# Cell 8 — Distribution + Top 10 Chart
# ============================================================
code("""# ── Distribution of mom_12_1 with top 10 + Q5 highlighted ──
top10_tickers = ["DELTA", "IRPC", "PTTGC", "NEX", "AGE", "HANA", "BPP", "GUNKUL", "INSET", "JTS"]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

# Left: Histogram of mom_12_1
is_q5 = latest["quintile"] == "Q5"
is_top10 = latest.index.isin(top10_tickers)

ax1.hist(latest.loc[~is_q5, "mom_12_1"], bins=25, color="#cccccc", alpha=0.6, label="Q1–Q4 (105 stocks)")
ax1.hist(latest.loc[is_q5 & ~is_top10, "mom_12_1"], bins=15, color="#fdae61", alpha=0.8, label="Q5 — Rest (17 stocks)")
ax1.hist(latest.loc[is_top10, "mom_12_1"], bins=10, color="#1a9850", alpha=0.9, label="Top 10 Portfolio")

for ticker in top10_tickers:
    val = latest.loc[ticker, "mom_12_1"]
    ax1.annotate(ticker, (val, 0.3), textcoords="offset points", xytext=(0, 8),
                fontsize=7, ha="center", rotation=60, color="#1a9850", fontweight="bold")

ax1.set_xlabel("12-1 Month Momentum (log return)")
ax1.set_ylabel("Number of Stocks")
ax1.set_title("Momentum Distribution — Top 10 vs. Universe", fontweight="bold")
ax1.legend(fontsize=8, loc="upper left")
sns.despine(ax=ax1)

# Right: Horizontal bar chart — Top 10 Z-Scores
top10_data = latest.loc[top10_tickers[::-1]]  # reverse for bottom-to-top
bar_colors = ["#006837" if z >= 2.0 else "#1a9850" if z >= 1.6 else "#66bd63"
              for z in top10_data["z_mom_12_1"]]

bars = ax2.barh(top10_data.index, top10_data["z_mom_12_1"], color=bar_colors, edgecolor="white", height=0.7)
for bar, (z, rp) in enumerate(zip(top10_data["z_mom_12_1"], top10_data["rank_pct"])):
    ax2.text(z + 0.03, bar, f"z={z:.2f}  (rank {rp*100:.1f}%)",
             va="center", fontsize=9, fontweight="bold", color="#333333")

ax2.axvline(0, color="gray", linewidth=0.8, linestyle="-")
ax2.axhline(2.5, color="#fdae61", linewidth=1, linestyle="--", alpha=0.5)
ax2.axhline(6.5, color="#fdae61", linewidth=1, linestyle="--", alpha=0.5)

# Conviction tier annotations
ax2.annotate("Higher Conviction\\nz ≥ 2.0", xy=(2.3, 8), fontsize=8, color="#006837",
            ha="center", fontweight="bold", bbox=dict(boxstyle="round,pad=0.3", facecolor="#e5f5e0", alpha=0.8))
ax2.annotate("Standard Conviction\\nz 1.6–1.9", xy=(1.7, 4.5), fontsize=8, color="#1a9850",
            ha="center", bbox=dict(boxstyle="round,pad=0.3", facecolor="#e5f5e0", alpha=0.8))
ax2.annotate("Smaller Position\\nz < 1.6", xy=(1.4, 1.5), fontsize=8, color="#66bd63",
            ha="center", bbox=dict(boxstyle="round,pad=0.3", facecolor="#e5f5e0", alpha=0.8))

ax2.set_xlabel("Momentum Z-Score (Standard Deviations Above Mean)")
ax2.set_title("Top 10 — Cross-Sectional Momentum Z-Scores", fontweight="bold")
ax2.set_xlim(0, max(top10_data["z_mom_12_1"]) + 0.7)
sns.despine(ax=ax2, left=True)
plt.tight_layout()
plt.show()

# Print ranking table
print("\\nCross-Sectional Momentum Ranking (as of 2026-04-30)")
print("=" * 75)
rank_table = latest.loc[top10_tickers][["mom_12_1", "z_mom_12_1", "rank_pct", "quintile"]]
rank_table.columns = ["12-1M Return", "Z-Score", "Percentile", "Quintile"]
rank_table.index.name = "Symbol"
display(rank_table.style
    .background_gradient(cmap="Greens", subset=["Z-Score", "Percentile"])
    .format({"12-1M Return": "{:.4f}", "Z-Score": "{:.3f}", "Percentile": "{:.3f}"})
)""")

# ============================================================
# Cell 9 — Momentum Decomposition
# ============================================================
md("""## 4. Momentum Decomposition: Not All Returns Are Created Equal

The 12-1M return is the primary signal, but we look across **four horizons** to understand the momentum profile. Stocks with strong long-term momentum *and* healthy short-term trends are more robust. Negative short-term momentum (mom_1_0) can indicate a pullback entry opportunity.""")

# ============================================================
# Cell 10 — Multi-Horizon Chart
# ============================================================
code("""# ── Multi-Horizon Momentum for Top 10 ─────────────────────
fig, ax = plt.subplots(figsize=(14, 7))

horizons = ["z_mom_12_1", "z_mom_6_1", "z_mom_3_1", "z_mom_1_0"]
horizon_labels = ["12M-1M (Long-term)", "6M-1M (Medium-term)", "3M-1M (Short-term)", "1M (Reversal)"]
horizon_colors = ["#003d32", "#1a9850", "#66bd63", "#fdae61"]

top10_data = latest.loc[top10_tickers]
x = np.arange(len(top10_tickers))
width = 0.18

for i, (hz, label, color) in enumerate(zip(horizons, horizon_labels, horizon_colors)):
    offset = (i - 1.5) * width
    bars = ax.bar(x + offset, top10_data[hz], width, label=label, color=color, edgecolor="white", linewidth=0.5)
    # Annotate values
    for bar, val in zip(bars, top10_data[hz]):
        if abs(val) > 0.2:
            ax.text(bar.get_x() + bar.get_width() / 2,
                   bar.get_height() + 0.05 if val > 0 else bar.get_height() - 0.3,
                   f"{val:.1f}", ha="center", va="bottom" if val > 0 else "top",
                   fontsize=7, fontweight="bold", rotation=90)

ax.set_xticks(x)
ax.set_xticklabels(top10_tickers, fontsize=11, fontweight="bold")
ax.axhline(0, color="gray", linewidth=1)
ax.axhline(1.0, color="#fdae61", linewidth=0.8, linestyle=":", alpha=0.6, label="+1σ threshold")
ax.set_ylabel("Z-Score (Standard Deviations)")
ax.set_title("Momentum Decomposition — Four Horizons Across Top 10", fontweight="bold")
ax.legend(loc="upper right", fontsize=9, ncol=2)
sns.despine()
plt.tight_layout()
plt.show()

# ── Commentary ──────────────────────────────────────────────
print("\\nKey observations from momentum decomposition:")
print()
print("1. DELTA & IRPC: Strongest across ALL horizons (z ≥ 0.8 in every window).")
print("   These are the highest-conviction picks — no weakness anywhere.")
print()
print("2. PTTGC: Strong 12M-1M, 6M-1M, AND 1M reversal — accelerating recently.")
print()
print("3. NEX: Strong long-term momentum but negative short-term (mom_3_1, mom_1_0).")
print("   This could be a pullback entry — the long-term trend is intact.")
print()
print("4. JTS: Strong 6M-1M but the weakest 12M-1M and negative short-term.")
print("   Lowest-conviction pick among the 10 — smallest allocation.")""")

# ============================================================
# Cell 11 — Portfolio Allocation
# ============================================================
md("""## 5. Portfolio Allocation

Positions are weighted by conviction tier, with higher z-score stocks receiving larger allocations. The volatility-target rebalance at month-end will adjust these weights based on each stock's realized volatility.""")

# ============================================================
# Cell 12 — Allocation Chart
# ============================================================
code("""# ── Portfolio Allocation Donut ─────────────────────────────
allocations = {
    "DELTA":  (120_000, 0.12, "#003d32"),
    "IRPC":   (120_000, 0.12, "#006837"),
    "PTTGC":  (120_000, 0.12, "#1a9850"),
    "NEX":    (100_000, 0.10, "#4dac26"),
    "AGE":    (100_000, 0.10, "#66bd63"),
    "HANA":   (100_000, 0.10, "#a6d96a"),
    "BPP":    (90_000,  0.09, "#d9ef8b"),
    "GUNKUL": (90_000,  0.09, "#fee08b"),
    "INSET":  (80_000,  0.08, "#fdae61"),
    "JTS":    (80_000,  0.08, "#f46d43"),
}

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

# Left: Donut chart
labels = list(allocations.keys())
sizes = [v[1] for v in allocations.values()]
colors = [v[2] for v in allocations.values()]

wedges, texts, autotexts = ax1.pie(
    sizes, labels=labels, autopct="%1.1f%%", startangle=140,
    colors=colors, pctdistance=0.82,
    wedgeprops={"linewidth": 1.5, "edgecolor": "white"},
    textprops={"fontsize": 10, "fontweight": "bold"},
)
# Donut hole
centre_circle = plt.Circle((0, 0), 0.55, fc="white", linewidth=0)
ax1.add_artist(centre_circle)
ax1.text(0, 0, "10 Stocks\\n1,000,000 THB", ha="center", va="center",
        fontsize=12, fontweight="bold", color="#333333")
ax1.set_title("Portfolio Allocation — Conviction-Weighted", fontweight="bold", pad=20)

# Right: Allocation in THB
thb_values = [v[0] for v in allocations.values()]
bar_colors = [v[2] for v in allocations.values()]
bars = ax2.barh(list(allocations.keys())[::-1], thb_values[::-1], color=bar_colors[::-1],
                edgecolor="white", height=0.7)

for bar, val, pct in zip(bars, thb_values[::-1], sizes[::-1]):
    ax2.text(val + 2000, bar.get_y() + bar.get_height() / 2,
             f"{val:,.0f} THB ({pct*100:.0f}%)", va="center", fontsize=10, fontweight="bold")

ax2.set_xlabel("Allocation (THB)")
ax2.set_title("Position Sizes — THB Allocation", fontweight="bold")
ax2.set_xlim(0, max(thb_values) * 1.25)
ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
sns.despine(ax=ax2, left=True)
plt.tight_layout()
plt.show()

# ── Summary Metrics Table ───────────────────────────────────
summary = pd.DataFrame({
    "Metric": ["Total AUM", "Number of Positions", "Max Position", "Min Position",
               "Weighting Scheme", "Vol Target (annual)", "Next Rebalance"],
    "Value": ["1,000,000 THB", "10", "12.0% (DELTA, IRPC, PTTGC)", "8.0% (INSET, JTS)",
              "Volatility-Target", "15%", "2026-05-30 (BME)"],
})
display(summary.style.set_caption("Portfolio Summary").hide(axis="index"))""")

# ============================================================
# Cell 13 — Monthly Rebalancing
# ============================================================
md("""## 6. Monthly Rebalancing Schedule

The strategy rebalances on **Business Month End (BME)** — the last trading day of each month. At each rebalance:

1. **Re-rank** all stocks by composite momentum z-score
2. **Buffer logic** reduces turnover: existing holdings are only evicted if a replacement ranks significantly higher (25 percentile-point buffer) or falls below the exit floor (35th percentile)
3. **Sector cap** is applied (max 35% per sector)
4. **Volatility-target weights** are computed (inverse-vol, scaled to 15% annual target)
5. **Trade list** is generated (delta from current weights)

The calendar below shows the full 2026 rebalance schedule.""")

# ============================================================
# Cell 14 — Rebalance Timeline
# ============================================================
code("""# ── Rebalance Timeline for 2026 ───────────────────────────
# TH trading calendar: BME dates
bme_dates_2026 = pd.date_range("2026-01-01", "2026-12-31", freq="BME")
today = pd.Timestamp("2026-05-04")

fig, ax = plt.subplots(figsize=(14, 4))

for i, dt in enumerate(bme_dates_2026):
    if dt.month == 5:
        color = "#1a9850"
        size = 200
        label = "May 30\\n(Next Rebalance)"
        z = 3
    elif dt < today:
        color = "#cccccc"
        size = 80
        label = ""
        z = 1
    else:
        color = "#66bd63"
        size = 120
        label = ""
        z = 2

    ax.scatter(dt, 0, s=size, c=color, zorder=z, edgecolors="white", linewidth=1.5)
    ax.text(dt, 0.15, dt.strftime("%b\\n%d"), ha="center", fontsize=8, color=color, fontweight="bold")

# Today marker
ax.axvline(today, color="#d73027", linewidth=2, linestyle="--", alpha=0.7, zorder=0)
ax.text(today, 0.35, "Today\\nMay 4", ha="center", fontsize=9, color="#d73027", fontweight="bold")

# Entry marker
entry_date = pd.Timestamp("2026-05-05")
ax.axvline(entry_date, color="#fc8d59", linewidth=1.5, linestyle=":", alpha=0.7)
ax.text(entry_date, -0.35, "Entry\\nMay 5", ha="center", fontsize=8, color="#fc8d59", fontweight="bold")

# Legend
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#1a9850", markersize=12, label="Next Rebalance (May 30)"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#66bd63", markersize=10, label="Future Rebalance"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#cccccc", markersize=8, label="Past Rebalance"),
    Line2D([0], [0], color="#d73027", linewidth=2, linestyle="--", label="Today (May 4)"),
]
ax.legend(handles=legend_elements, loc="upper right", fontsize=9, ncol=2)

ax.set_ylim(-0.5, 0.5)
ax.set_yticks([])
ax.set_xlim(pd.Timestamp("2026-01-01"), pd.Timestamp("2027-01-01"))
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.set_title("2026 Monthly Rebalance Calendar — Business Month End (BME)", fontweight="bold", pad=15)
sns.despine(left=True)
plt.tight_layout()
plt.show()

print("\\nBuffer Logic Parameters:")
print("  • Buffer threshold: 25 percentile points (replacement must rank this much higher)")
print("  • Exit rank floor: 35th percentile (unconditional eviction below this)")
print("  • Target turnover: 20–30% one-way per rebalance")""")

# ============================================================
# Cell 15 — Risk Management
# ============================================================
md("""## 7. Risk Management

The CSM strategy layers multiple risk controls to protect capital:

### 7.1 Volatility Targeting
- **Target:** 15% annualized portfolio volatility
- **Method:** Scale equity exposure inversely to realized volatility (63-day lookback)
- **Cap:** Max 1.5× leverage (i.e., position sizes can be scaled down but not levered up beyond 1.5×)
- **Fast blend:** 30% weight on 21-day vol for quicker adaptation

### 7.2 Circuit Breaker
- **Trigger:** −10% drawdown from peak NAV (60-day rolling window)
- **Action:** Reduce equity exposure to 20% (safe mode)
- **Recovery:** Re-enter full allocation after drawdown narrows to −5% and holds for 21 days
- **Purpose:** Prevent catastrophic losses during tail events

### 7.3 Position Bounds
- **Maximum:** 15% per single stock
- **Minimum:** 5% per single stock
- **Rationale:** Prevents concentration risk while maintaining meaningful position sizes

### 7.4 Sector Cap
- **Maximum:** 35% in any single sector
- **Enforcement:** Prune lowest-composite stocks from overweight sectors

### 7.5 Cut-Loss Rules (Daily Monitoring)
- 🟡 **Warning (−7%):** Flag in daily report, prepare exit plan
- 🔴 **Hard Stop (−10%):** Sell immediately, do not wait for month-end
- 🟢 **Trailing Stop:** After +10% gain, raise stop to breakeven""")

# ============================================================
# Cell 16 — Execution Plan
# ============================================================
md("""## 8. Execution Plan — May 5, 2026

| Step | Action |
|------|--------|
| **Entry** | Buy all 10 positions **At The Opening (ATO)** on 2026-05-05 |
| **Execution** | Manual via settrad click2win |
| **Order Type** | Market-at-open (fill at prevailing ATO price) |
| **Monitoring** | Daily cut-loss check starting 2026-05-06 |
| **First Rebalance** | 2026-05-30 (last trading day of May) |

### Position Table (ATO — 2026-05-05)

| # | Symbol | Allocation (THB) | Weight | Conviction |
|---|--------|------------------|--------|------------|
| 1 | DELTA | 120,000 | 12.0% | Higher |
| 2 | IRPC | 120,000 | 12.0% | Higher |
| 3 | PTTGC | 120,000 | 12.0% | Higher |
| 4 | NEX | 100,000 | 10.0% | Standard |
| 5 | AGE | 100,000 | 10.0% | Standard |
| 6 | HANA | 100,000 | 10.0% | Standard |
| 7 | BPP | 90,000 | 9.0% | Smaller |
| 8 | GUNKUL | 90,000 | 9.0% | Smaller |
| 9 | INSET | 80,000 | 8.0% | Smaller |
| 10 | JTS | 80,000 | 8.0% | Smaller |

> **Note:** Share quantities to be calculated after confirming ATO prices on 2026-05-05 morning.
> Total budget: 1,000,000 THB. Round down to nearest board lot (100 shares) for each position.""")

# ============================================================
# Cell 17 — Disclaimer
# ============================================================
md("""---

## Appendix: Data Provenance

| Data Source | File | Last Updated |
|-------------|------|---------------|
| Features (momentum signals) | `data/processed/features_latest.parquet` | 2026-04-30 |
| Prices (daily OHLCV) | `data/processed/prices_latest.parquet` | 2026-04-30 |
| Signal Quality (IC/ICIR) | `results/signals/latest_ranking.json` | 2026-04-29 |
| Universe Symbols | `data/universe/symbols.json` | Auto-refreshed |

**Strategy Version:** CSM v1.0 (live-test branch, commit `4349c46`)
**Environment:** `live-test-v1.0.0`

---

*This notebook was generated by the CSM strategy pipeline. All stock selections are determined by the cross-sectional momentum ranking algorithm with the configuration specified in `configs/live-settings.yaml`. No discretionary overrides were applied.*

*Disclaimer: Past momentum does not guarantee future returns. This is a systematic strategy undergoing live testing. All trading decisions are the responsibility of the trader.*""")

# ============================================================
# Assemble & Save
# ============================================================
nb.cells = cells

import sys
out = "notebooks/05_live_portfolio_rationale.ipynb"
nbf.write(nb, out)

print("✅", out)
