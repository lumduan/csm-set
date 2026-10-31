"""Phase C.3 parameter review: re-run the Phase 4.8 notebook's stress tests on the live 2026 path.

Read-only. Inputs: db_gateway.daily_performance (NAV, cash), the published daily logs
(holdings at each
evaluation, sector/position weights), tvkit closes (px_tvkit.csv). Engine classes run unmodified:
VolatilityScaler, DrawdownCircuitBreaker. Writes results.json next to this file.
"""

from __future__ import annotations

import json
import math
import os
import pathlib
import re
import subprocess

import numpy as np
import pandas as pd

from csm.portfolio.drawdown_circuit_breaker import (
    CircuitBreakerState,
    DrawdownCircuitBreaker,
    DrawdownCircuitBreakerConfig,
)
from csm.portfolio.vol_scaler import VolatilityScaler, VolScalingConfig

HERE = pathlib.Path(__file__).resolve().parent
LT = HERE.parents[1]  # docs/live-test
PX = pathlib.Path(
    os.environ.get("PX_CSV", str(HERE / "px_tvkit.csv"))
)  # written by fetch_px.py; gitignored


def psql(sql):
    out = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "PGOPTIONS=-c default_transaction_read_only=on",
            "quant-postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "db_gateway",
            "-At",
            "-F",
            "|",
            "-c",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [ln.split("|") for ln in out.strip().splitlines() if ln]


rows_ = psql(
    "SELECT time::date, total_value, cash_balance FROM daily_performance"
    " WHERE strategy_id='csm-set' ORDER BY time"
)
nav = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in rows_})
cash = pd.Series({pd.Timestamp(r[0]): float(r[2]) for r in rows_})
# published post-trade values on the two rotation days whose fills landed after the refresh
nav[pd.Timestamp("2026-08-03")] = 1247760.70
cash[pd.Timestamp("2026-08-03")] = 3027.70
nav[pd.Timestamp("2026-10-01")] = 1352210.89
cash[pd.Timestamp("2026-10-01")] = 1377.89
flow = pd.Series(0.0, index=nav.index)
flow[pd.Timestamp("2026-06-04")] = 100000.0
flow[pd.Timestamp("2026-08-03")] = 20000.0
r_book = ((nav - flow) / nav.shift(1) - 1).dropna()  # 121 sessions, 2026-05-05 .. 2026-10-30
w_eq = ((nav - cash) / nav).shift(1).reindex(r_book.index)  # equity share at the prior close
r_eq = r_book / w_eq  # equity-sleeve return
print(
    "sessions",
    len(r_book),
    r_book.index[0].date(),
    r_book.index[-1].date(),
    "mean equity share",
    round(float(w_eq.mean()), 4),
)


def metrics(r: pd.Series) -> dict:
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    sd = float(r.std(ddof=1))
    rf = 0.02 / 252
    return dict(
        total=float(eq.iloc[-1] - 1),
        vol=sd * math.sqrt(252),
        sharpe0=float(r.mean()) / sd * math.sqrt(252) if sd else 0.0,
        sharpe2=float((r - rf).mean()) / sd * math.sqrt(252) if sd else 0.0,
        maxdd=float(dd.min()),
        maxdd_date=str(dd.idxmin().date()),
    )


actual = metrics(r_book)
print("actual", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in actual.items()})


# ---- holdings at each evaluation (from the published logs)
def holdings(day: str) -> dict:
    t = (LT / f"daily/{day}.md").read_text()
    L = t.splitlines()
    i = next(k for k, ln in enumerate(L) if ln.startswith("| # | Symbol"))
    out = {}
    for ln in L[i + 2 :]:
        if not ln.startswith("|"):
            break
        c = [x.strip().strip("*") for x in ln.strip().strip("|").split("|")]
        out[c[1]] = float(c[5].replace(",", ""))
    return out


EVAL = [
    "2026-05-05",
    "2026-05-29",
    "2026-06-30",
    "2026-07-31",
    "2026-08-31",
    "2026-09-30",
]  # 05-05 = entry book
px = pd.read_csv(PX, index_col="date", parse_dates=True)
sessions = list(r_book.index)


def period(i: int) -> list:
    start = pd.Timestamp(EVAL[i])
    end = pd.Timestamp(EVAL[i + 1]) if i + 1 < len(EVAL) else pd.Timestamp("2026-10-30")
    lo = start if i == 0 else start + pd.Timedelta(days=1)
    return [s for s in sessions if lo <= s <= end]


# ---- 1. vol scaling (notebook §3): engine VolatilityScaler at each evaluation,
#         on the then-held book
def vol_fracs(target: float, blend: float, lookback: int = 63) -> list:
    cfg = VolScalingConfig(
        target_annual=target,
        lookback_days=lookback,
        cap=1.5,
        fast_lookback_days=21,
        fast_blend_weight=blend,
    )
    out = []
    for i, e in enumerate(EVAL):
        hd = holdings(e)
        w = pd.Series(hd)
        w = w / w.sum()
        asof = (
            pd.Timestamp(e) - pd.Timedelta(days=1) if i == 0 else pd.Timestamp(e)
        )  # entry: vol known at the 05-04 close
        _, res = VolatilityScaler().scale(w, px.loc[:asof, list(hd)], cfg)
        out.append(
            (
                res.equity_fraction,
                res.realized_vol_annual,
                res.slow_realized_vol,
                res.fast_realized_vol,
            )
        )
    return out


def apply_fracs(fr: list) -> pd.Series:
    f = pd.Series(1.0, index=r_book.index)
    for i in range(len(EVAL)):
        for s in period(i):
            f[s] = fr[i]
    return (
        f * r_book
    )  # the overlay scales the whole book; f = 1 reproduces the published series exactly


res = {"actual": actual, "sessions": len(r_book), "mean_equity_share": float(w_eq.mean())}
vgrid = {}
for tgt in (0.10, 0.15, 0.20, 0.25, 0.30):
    for bl in (0.0, 0.3):
        fr = vol_fracs(tgt, bl)
        r = apply_fracs([x[0] for x in fr])
        vgrid[f"{tgt:.2f}/{bl:.1f}"] = dict(
            fracs=[round(x[0], 4) for x in fr], vols=[round(x[1], 4) for x in fr], **metrics(r)
        )
res["vol_grid"] = vgrid
base = vol_fracs(0.15, 0.3)
print(
    "vol 15%/0.3 equity fractions",
    [round(x[0], 3) for x in base],
    "realized",
    [round(x[1], 3) for x in base],
)


# ---- 2. circuit breaker (notebook §4): engine DrawdownCircuitBreaker threaded every
#         session on the counterfactual path
def run_breaker(
    trigger: float,
    window: int,
    recov_ratio: float = 0.5,
    confirm: int = 21,
    acting: str = "monthly",
    vol_f: list | None = None,
    r_in: pd.Series | None = None,
):
    recov_gap = round(-trigger * (1 - recov_ratio), 6)  # design ratio: trip −10% → recover −5%
    r_in = r_book if r_in is None else r_in
    cfg = DrawdownCircuitBreakerConfig(
        window_days=window,
        trigger_threshold=trigger,
        recovery_threshold=trigger + recov_gap,
        recovery_buffer=recov_gap,
        recovery_confirm_days=confirm,
        safe_mode_max_equity=0.20,
    )
    brk = DrawdownCircuitBreaker()
    state = CircuitBreakerState.NORMAL
    prog = 0
    hist_nav = list(nav.loc[: pd.Timestamp("2026-05-04")].values)  # seed
    vf = pd.Series(1.0, index=r_in.index)
    if vol_f is not None:
        for i in range(len(EVAL)):
            for s in period(i):
                vf[s] = vol_f[i]
    f_brk = 1.0
    out = []
    trips = []
    nv = hist_nav[-1]
    states = []
    month_end = set(pd.Timestamp(x) for x in EVAL[1:]) | {pd.Timestamp("2026-10-30")}
    for s in r_in.index:
        rr = vf[s] * f_brk * r_in[s]
        out.append(rr)
        nv = nv * (1 + rr)
        hist_nav.append(nv)
        eqc = pd.Series(hist_nav, index=pd.RangeIndex(len(hist_nav)))
        _, cb = brk.apply(
            pd.Series({"x": 1.0}), eqc, cfg, current_state=state, recovery_progress_days=prog
        )
        new = CircuitBreakerState(cb.current_state)
        prog = cb.recovery_progress_days
        if new != state and new == CircuitBreakerState.TRIPPED:
            trips.append(str(s.date()))
        state = new
        states.append(state.value)
        if acting == "daily" or (acting == "monthly" and s in month_end):
            f_brk = 0.2 if state != CircuitBreakerState.NORMAL else 1.0
    r = pd.Series(out, index=r_in.index)
    return (
        dict(
            trips=trips,
            final_state=state.value,
            sessions_scaled=int(sum(1 for x in states if x != CircuitBreakerState.NORMAL.value)),
            **metrics(r),
        ),
        r,
        states,
    )


bgrid = {}
for trig in (-0.05, -0.075, -0.10, -0.125, -0.15):
    for win in (40, 60, 120):
        for act in ("monthly", "daily"):
            d, r, stt = run_breaker(trig, win, acting=act)
            bgrid[f"{trig:+.3f}/{win}/{act}"] = d
res["breaker_grid"] = bgrid
for k in (
    "-0.100/60/monthly",
    "-0.050/60/monthly",
    "-0.075/60/monthly",
    "-0.050/60/daily",
    "-0.075/60/daily",
    "-0.100/60/daily",
):
    print("breaker", k, bgrid[k]["trips"], round(bgrid[k]["total"], 4), round(bgrid[k]["maxdd"], 4))
# combined: vol 15% (blend 0.3) then breaker −10%/60 monthly, as the engine orders them
# (the breaker scales post-scaler weights)
d, r, _ = run_breaker(-0.10, 60, vol_f=[x[0] for x in base])
res["combined_vol15_brk10"] = d
print("combined", d["trips"], round(d["total"], 4), round(d["vol"], 4), round(d["maxdd"], 4))
# ---- 3. block bootstrap (notebook §9b): circular 21-session blocks of the live book's
#         daily returns, 252-session paths
rng = np.random.default_rng(42)
N = 2000
L_ = 252
B = 21
arr = r_book.to_numpy()
n = len(arr)


def boot_path():
    out = []
    while len(out) < L_:
        st_ = rng.integers(0, n)
        out.extend(arr[(st_ + np.arange(B)) % n])
    return np.array(out[:L_])


def sim(path, trigger=-0.10, window=60, monthly=True, vol_target=None):
    navp = [1.0]
    f_brk = 1.0
    state = "normal"
    prog = 0
    trips = 0
    scaled = 0
    f_vol = 1.0
    for t, re_ in enumerate(path):
        if vol_target is not None and t % 21 == 0:
            hist = path[max(0, t - 63) : t] if t >= 21 else arr[-63:]
            rv = (
                float(np.std(hist) * math.sqrt(252))
                if len(hist) >= 21
                else float(np.std(arr) * math.sqrt(252))
            )
            f_vol = min(vol_target / rv, 1.0) if rv > 0 else 1.0
        rr = f_vol * f_brk * re_
        navp.append(navp[-1] * (1 + rr))
        win = navp[-(window + 1) :]
        dd = navp[-1] / max(win) - 1
        rec = trigger * 0.5
        if state == "normal" and dd <= trigger:
            state = "tripped"
            trips += 1
        elif state == "tripped" and dd > rec:
            state = "recovering"
            prog = 1
        elif state == "recovering":
            if dd > rec:
                prog += 1
                if prog >= 21:
                    state = "normal"
                    prog = 0
            else:
                state = "tripped"
                prog = 0
        if (not monthly) or (t + 1) % 21 == 0:
            f_brk = 0.2 if state != "normal" else 1.0
        scaled += f_brk < 1.0
    e = np.array(navp)
    dd = e / np.maximum.accumulate(e) - 1
    rets = np.diff(e) / e[:-1]
    return dict(
        total=e[-1] - 1,
        maxdd=dd.min(),
        trips=trips,
        scaled=scaled,
        sharpe=float(rets.mean() / rets.std(ddof=1) * math.sqrt(252)) if rets.std() > 0 else 0.0,
    )


def sim_states(path, trigger, window):
    navp = [float(nav.iloc[0])]
    state = "normal"
    prog = 0
    out = []
    rec = trigger * 0.5
    for re_ in path:
        navp.append(navp[-1] * (1 + re_))
        win = navp[-(window + 1) :]
        dd = navp[-1] / max(win) - 1
        if state == "normal" and dd <= trigger:
            state = "tripped"
        elif state == "tripped" and dd > rec:
            state = "recovering"
            prog = 1
        elif state == "recovering":
            if dd > rec:
                prog += 1
                if prog >= 21:
                    state = "normal"
                    prog = 0
            else:
                state = "tripped"
                prog = 0
        out.append(state)
    return out


equiv = {}
for trig in (-0.05, -0.075, -0.10):
    _, _, cls_states = run_breaker(trig, 60, acting="never")
    mine = sim_states(r_book.to_numpy(), trig, 60)
    equiv[f"{trig:+.3f}"] = dict(
        sessions=len(mine),
        agree=sum(1 for a_, b_ in zip(cls_states, mine, strict=True) if a_.lower() == b_),
        class_trips=[
            str(s.date())
            for s, a_, b_ in zip(
                r_book.index, ["NORMAL"] + cls_states[:-1], cls_states, strict=True
            )
            if a_ != "TRIPPED" and b_ == "TRIPPED"
        ],
    )
print("equivalence (class vs re-implementation, f = 1, daily state)", equiv)
res["bootstrap_equivalence"] = equiv
paths = [boot_path() for _ in range(N)]


def summ(rs):
    tot = np.array([x["total"] for x in rs])
    mdd = np.array([x["maxdd"] for x in rs])
    sh = np.array([x["sharpe"] for x in rs])
    tr = np.array([x["trips"] for x in rs])
    sc = np.array([x["scaled"] for x in rs])
    return dict(
        total_p05=float(np.percentile(tot, 5)),
        total_p50=float(np.median(tot)),
        total_p95=float(np.percentile(tot, 95)),
        maxdd_p05=float(np.percentile(mdd, 5)),
        maxdd_p50=float(np.median(mdd)),
        sharpe_p50=float(np.median(sh)),
        p_trip=float((tr > 0).mean()),
        mean_trips=float(tr.mean()),
        mean_scaled_share=float(sc.mean() / L_),
        p_dd_worse_15=float((mdd < -0.15).mean()),
    )


boot = {}
boot["none"] = summ([sim(p, trigger=-9.0) for p in paths])
for trig in (-0.075, -0.10, -0.15):
    boot[f"breaker{trig:+.3f}"] = summ([sim(p, trigger=trig) for p in paths])
boot["vol0.15"] = summ([sim(p, trigger=-9.0, vol_target=0.15) for p in paths])
boot["vol0.15+breaker-0.100"] = summ([sim(p, trigger=-0.10, vol_target=0.15) for p in paths])
boot["vol0.25"] = summ([sim(p, trigger=-9.0, vol_target=0.25) for p in paths])
res["bootstrap"] = dict(N=N, path_len=L_, block=B, seed=42, **boot)
for k, v in boot.items():
    print("boot", k, {a: round(b, 4) for a, b in v.items()})
# ---- 4. sector cap and position band, measured on every published log since 2026-05-20
sec_rows = []
for p in sorted((LT / "daily").glob("2026-*.md")):
    t = p.read_text()
    if "| Sector |" not in t or "### Account summary" not in t:
        continue
    L = t.splitlines()
    i = next(k for k, ln in enumerate(L) if ln.startswith("| Sector |"))
    ws = {}
    for ln in L[i + 2 :]:
        if not ln.startswith("|"):
            break
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        ws[c[0]] = float(c[2].replace("*", "").replace("%", ""))
    m = re.search(r"\| \**Total NAV\** \| \**([\d,]+\.\d\d)", t)
    navd = float(m.group(1).replace(",", ""))
    pos = {k: v / navd * 100 for k, v in holdings(p.stem).items()}
    sec_rows.append(
        dict(
            date=p.stem,
            max_sector=max(ws.values()),
            max_sector_name=max(ws, key=ws.get),
            n_over35=sum(1 for v in ws.values() if v > 35),
            max_pos=max(pos.values()),
            min_pos=min(pos.values()),
            n_pos_over15=sum(1 for v in pos.values() if v > 15),
            n_pos_under5=sum(1 for v in pos.values() if v < 5),
            top2=sum(sorted(ws.values())[-2:]),
        )
    )
sdf = pd.DataFrame(sec_rows)
res["bands"] = dict(
    sessions=len(sdf),
    first=sdf.date.iloc[0],
    last=sdf.date.iloc[-1],
    sessions_sector_over35=int((sdf.max_sector > 35).sum()),
    sessions_sector_over30=int((sdf.max_sector > 30).sum()),
    sessions_sector_over40=int((sdf.max_sector > 40).sum()),
    max_sector=float(sdf.max_sector.max()),
    max_sector_date=sdf.loc[sdf.max_sector.idxmax(), "date"],
    max_sector_name=sdf.loc[sdf.max_sector.idxmax(), "max_sector_name"],
    sessions_pos_over15=int((sdf.n_pos_over15 > 0).sum()),
    sessions_pos_under5=int((sdf.n_pos_under5 > 0).sum()),
    top2_min=float(sdf.top2.min()),
    top2_max=float(sdf.top2.max()),
    by_month={
        m_: dict(
            sessions=int(g.shape[0]),
            over35=int((g.max_sector > 35).sum()),
            max=float(g.max_sector.max()),
            pos_breach=int(((g.n_pos_over15 > 0) | (g.n_pos_under5 > 0)).sum()),
        )
        for m_, g in sdf.groupby(sdf.date.str[:7])
    },
)
print("bands", json.dumps(res["bands"], indent=0)[:1500])
(HERE / "results.json").write_text(json.dumps(res, indent=1, default=str))
print("wrote results.json")
