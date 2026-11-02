"""Fetch daily OHLCV via tvkit for every name the live book traded (input for slippage_audit.py).

Writes ohlc_tvkit.csv next to this file (gitignored).
"""

import asyncio
import pathlib

import pandas as pd
from tvkit.api.chart.ohlcv import OHLCV

NAMES = [
    "DELTA",
    "PTTGC",
    "NEX",
    "AGE",
    "JTS",
    "KCE",
    "EASTW",
    "MCOT",
    "FORTH",
    "SMT",
    "MGC",
    "EPG",
    "CNT",
    "SPRC",
    "SSP",
    "INSET",
    "IRPC",
    "GUNKUL",
    "HANA",
]


async def one(s):
    async with OHLCV() as o:
        return await o.get_historical_ohlcv("SET:" + s, interval="1D", bars_count=200)


rows = []
for s in NAMES:
    for x in asyncio.run(one(s)):
        rows.append(
            (
                s,
                str(
                    pd.Timestamp(x.timestamp, unit="s", tz="UTC").tz_convert("Asia/Bangkok").date()
                ),
                x.open,
                x.high,
                x.low,
                x.close,
                x.volume,
            )
        )
out = pathlib.Path(__file__).resolve().parent / "ohlc_tvkit.csv"
pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"]).to_csv(
    out, index=False
)
print(len(rows))
