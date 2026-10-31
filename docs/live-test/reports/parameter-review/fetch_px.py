"""Fetch daily closes via tvkit for every name the live book held, plus SET.

Input for param_review.py; writes px_tvkit.csv (gitignored).
"""

import asyncio
import pathlib

import pandas as pd
from tvkit.api.chart.ohlcv import OHLCV

NAMES = [
    "DELTA",
    "IRPC",
    "PTTGC",
    "NEX",
    "AGE",
    "HANA",
    "GUNKUL",
    "INSET",
    "JTS",
    "KCE",
    "EASTW",
    "KKP",
    "LHFG",
    "MCOT",
    "FORTH",
    "SMT",
    "MGC",
    "EPG",
    "CNT",
    "SET",
]


async def one(sym):
    async with OHLCV() as o:
        return await o.get_historical_ohlcv("SET:" + sym, interval="1D", bars_count=700)


cols = {}
for s in NAMES:
    try:
        b = asyncio.run(one(s))
        cols[s] = pd.Series(
            {
                pd.Timestamp(x.timestamp, unit="s", tz="UTC")
                .tz_convert("Asia/Bangkok")
                .normalize()
                .tz_localize(None): x.close
                for x in b
            }
        )
        print(s, len(b), cols[s].index[0].date(), cols[s].index[-1].date())
    except Exception as e:
        print(s, "FAILED", type(e).__name__, str(e)[:120])
df = pd.DataFrame(cols).sort_index()
df.index.name = "date"
df.to_csv(pathlib.Path(__file__).resolve().parent / "px_tvkit.csv")
print(df.shape)
