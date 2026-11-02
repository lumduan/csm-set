"""Phase C.2 slippage audit: the engine slippage model against the live fills and quotes.

Read-only. Inputs:
- fills.json: every rotation fill since 2026-06-02, transcribed from the published daily logs;
- ohlc_tvkit.csv: daily OHLCV from tvkit (written by fetch_ohlc.py, gitignored);
- the order-book capture's compacted store (quant-orderbook-engine/data/cold_sp), read-only:
  SP_DepthV1 (quotes) and SP_MarketTickerV1 (trades).
The engine model is csm.execution.slippage.SqrtImpactSlippageModel, run unmodified with the config
ExecutionSimulator actually constructs. Writes results.json next to this file.
"""

from __future__ import annotations

import json
import math
import os
import pathlib
from decimal import Decimal as D

import pandas as pd

from csm.execution.slippage import SlippageModelConfig, SqrtImpactSlippageModel

HERE = pathlib.Path(__file__).resolve().parent
COLD = pathlib.Path(
    os.environ.get(
        "COLD_SP",
        str(HERE.parents[5] / "quant-orderbook-engine/data/cold_sp"),
    )
)
FEE = 0.0016799
fills = json.loads((HERE / "fills.json").read_text())["fills"]
ohlc = pd.read_csv(HERE / "ohlc_tvkit.csv")
ohlc["date"] = ohlc["date"].astype(str)
model = SqrtImpactSlippageModel()  # ExecutionSimulator.__init__ builds it with the DEFAULT config
cfg = SlippageModelConfig()
res: dict = {"model": {"half_spread_bps": cfg.half_spread_bps, "impact_coef": cfg.impact_coef}}


def bar(sym: str, day: str) -> pd.Series:
    return ohlc[(ohlc.symbol == sym) & (ohlc.date == day)].iloc[0]


def adtv63(sym: str, day: str) -> float:
    """63-session ADTV up to the session BEFORE the trade (the evaluation close)."""
    h = ohlc[(ohlc.symbol == sym) & (ohlc.date < day)].tail(63)
    return float((h.close * h.volume).mean())


# ---- 1. fills: cost against the decision price, the day's open and the day's close
rows = []
for day, side, sym, n, fill, dec, close in fills:
    b = bar(sym, day)
    sgn = 1 if side == "BUY" else -1  # positive = cost to the book
    F = float(fill)
    notional = n * F
    prev = ohlc[(ohlc.symbol == sym) & (ohlc.date < day)].iloc[-1]
    dec_px = float(dec) if dec is not None else None
    r = {
        "date": day,
        "side": side,
        "symbol": sym,
        "shares": n,
        "fill": F,
        "notional": round(notional, 2),
        "decision": dec_px,
        "open": float(b.open),
        "high": float(b.high),
        "low": float(b.low),
        "close": float(b.close),
        "published_close": float(close),
        "fill_eq_open": bool(abs(F - b.open) < 1e-9),
        "fill_eq_close": bool(abs(F - b.close) < 1e-9),
        "in_range": bool(b.low - 1e-9 <= F <= b.high + 1e-9),
        "vs_decision_thb": None if dec_px is None else round(sgn * (F - dec_px) * n, 2),
        "vs_decision_bps": None if dec_px is None else round(sgn * (F / dec_px - 1) * 1e4, 1),
        "vs_open_thb": round(sgn * (F - b.open) * n, 2),
        "vs_open_bps": round(sgn * (F / b.open - 1) * 1e4, 1),
        "vs_close_thb": round(sgn * (F - b.close) * n, 2),
        "vs_close_bps": round(sgn * (F / b.close - 1) * 1e4, 1),
        "gap_bps": None if dec_px is None else round((b.open / dec_px - 1) * 1e4, 1),
        "prev_close_vendor": float(prev.close),
    }
    adtv = adtv63(sym, day)
    part = notional / adtv
    r["adtv63_thb"] = round(adtv, 2)
    r["participation"] = part
    est = model.estimate(notional, adtv)
    r["model_bps"] = round(est, 3)
    r["model_thb"] = round(est / 1e4 * notional, 2)
    r["model_thb_exact"] = est / 1e4 * notional
    r["fee_thb"] = round(notional * FEE, 2)
    rows.append(r)
check_close = all(abs(r["close"] - r["published_close"]) < 1e-9 for r in rows)
res["fills"] = rows
res["published_close_equals_vendor_close"] = check_close


def summarise(sel: list[dict]) -> dict:
    nt = sum(r["notional"] for r in sel)
    out = {"fills": len(sel), "notional": round(nt, 2)}
    for k in ("vs_decision", "vs_open", "vs_close"):
        s = [r for r in sel if r[f"{k}_thb"] is not None]
        thb = sum(r[f"{k}_thb"] for r in s)
        nn = sum(r["notional"] for r in s)
        out[f"{k}_thb"] = round(thb, 2)
        out[f"{k}_bps"] = round(thb / nn * 1e4, 1) if nn else None
        out[f"{k}_n"] = len(s)
    out["model_thb"] = round(sum(r["model_thb_exact"] for r in sel), 2)
    out["model_bps"] = round(out["model_thb"] / nt * 1e4, 2)
    out["fees_thb"] = round(sum(r["fee_thb"] for r in sel), 2)
    out["fill_eq_open"] = int(sum(bool(r["fill_eq_open"]) for r in sel))
    out["fill_eq_close"] = int(sum(bool(r["fill_eq_close"]) for r in sel))
    out["in_range"] = int(sum(bool(r["in_range"]) for r in sel))
    return out


res["by_rotation"] = {
    d: summarise([r for r in rows if r["date"] == d]) for d in sorted({r["date"] for r in rows})
}
res["all"] = summarise(rows)

# ---- 2. the captured tape: opening auction and what traded at the reported price
tape = {}
for day, sym, side, n, fill in (
    ("2026-08-03", "DELTA", "SELL", 300, "272.00"),
    ("2026-10-01", "MGC", "SELL", 9200, "6.45"),
    ("2026-10-01", "CNT", "BUY", 18200, "3.34"),
):
    f = COLD / f"date={day}/class=equity/series={sym}/SP_MarketTickerV1.parquet"
    mt = pd.read_parquet(f, columns=["t_ingest_ns", "price", "volume", "sequence"])
    mt = mt.sort_values("sequence")
    mt["p"] = mt.price.astype(str).map(D)
    first = mt.iloc[0]
    open_vol = int(mt[(mt.t_ingest_ns == first.t_ingest_ns) & (mt.p == first.p)].volume.sum())
    b = bar(sym, day)
    tape[f"{day} {sym}"] = {
        "side": side,
        "shares": n,
        "reported": float(fill),
        "tape_rows": len(mt),
        "tape_volume": int(mt.volume.sum()),
        "vendor_volume": int(b.volume),
        "tape_share_of_vendor": round(mt.volume.sum() / b.volume * 100, 2),
        "opening_print": float(first.p),
        "opening_print_volume": open_vol,
        "opening_time_utc": str(pd.Timestamp(int(first.t_ingest_ns)).tz_localize("UTC")),
        "closing_print": float(mt.iloc[-1].p),
        "volume_at_reported": int(mt[mt.p == D(fill)].volume.sum()),
        "vendor_open": float(b.open),
        "vendor_close": float(b.close),
    }
res["tape"] = tape

# ---- 3. quoted spreads from the captured depth (continuous phases 2 and 4, uncrossed)
spreads = {}
for day, syms in (
    ("2026-10-30", ["KCE", "IRPC", "GUNKUL", "HANA", "SPRC"]),
    ("2026-08-03", ["DELTA"]),
):
    for sym in syms:
        f = COLD / f"date={day}/class=equity/series={sym}/SP_DepthV1.parquet"
        dp = pd.read_parquet(
            f, columns=["t_ingest_ns", "phase", "crossed", "bid_levels", "ask_levels"]
        )
        dp = dp.sort_values("t_ingest_ns").reset_index(drop=True)
        dp["dt"] = dp.t_ingest_ns.shift(-1) - dp.t_ingest_ns
        keep = dp[dp.phase.isin([2, 4]) & (dp.crossed.fillna(False) == False)].copy()  # noqa: E712
        bid = keep.bid_levels.map(
            lambda s: max(float(x[0]) for x in json.loads(s)) if json.loads(s) else math.nan
        )
        ask = keep.ask_levels.map(
            lambda s: min(float(x[0]) for x in json.loads(s)) if json.loads(s) else math.nan
        )
        keep["spread"] = ask - bid
        keep["mid"] = (ask + bid) / 2
        keep = keep[(keep.spread > 0) & keep.mid.notna()]
        keep["bps"] = keep.spread / keep.mid * 1e4
        lv = json.loads(keep.bid_levels.iloc[len(keep) // 2])
        tick = min(
            round(float(lv[i][0]) - float(lv[i + 1][0]), 6)
            for i in range(len(lv) - 1)
            if float(lv[i][0]) > float(lv[i + 1][0])
        )
        w = keep.dt.clip(upper=300e9).fillna(0)
        order = keep.bps.sort_values().index
        cum = w.loc[order].cumsum() / w.sum()
        tw_median = float(keep.bps.loc[order][cum >= 0.5].iloc[0])
        ticks = (keep.spread / tick).round().astype(int)
        spreads[f"{day} {sym}"] = {
            "snapshots": len(keep),
            "tick": tick,
            "mid_median": round(float(keep.mid.median()), 4),
            "spread_bps_time_weighted_median": round(tw_median, 1),
            "spread_bps_mean": round(float(keep.bps.mean()), 1),
            "one_tick_share": round(float((ticks == 1).mean()), 4),
            "half_spread_bps_time_weighted_median": round(tw_median / 2, 1),
            "one_tick_bps_at_median_mid": round(tick / float(keep.mid.median()) * 1e4, 1),
        }
res["spreads"] = spreads
(HERE / "results.json").write_text(json.dumps(res, indent=1, default=str))
print(
    json.dumps({k: v for k, v in res.items() if k not in ("fills",)}, indent=1, default=str)[:6000]
)
