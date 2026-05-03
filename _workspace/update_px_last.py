"""Update PX_LAST in S&P500_filtered.xlsx with the latest closes from Yahoo Finance.

- Backs up the file with a timestamp suffix.
- Reads every sheet, modifies only PX_LAST, writes the whole workbook back.
- Bloomberg → Yahoo: first whitespace-token, '/' → '-' (uppercased).
- Drops days where every column is NaN; deduplicates dates.

Run:
  python _workspace/update_px_last.py
"""
from __future__ import annotations

import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

PATH = Path("data/S&P500_filtered.xlsx")


def bb_to_yahoo(t: str) -> str:
    return t.split()[0].replace("/", "-").upper()


def main() -> int:
    if not PATH.exists():
        print(f"missing: {PATH}")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = PATH.with_suffix(f".backup-{ts}.xlsx")
    shutil.copy(PATH, backup)
    print(f"backup -> {backup}")

    print("reading all sheets ...")
    all_sheets = pd.read_excel(PATH, sheet_name=None, engine="openpyxl")
    px = all_sheets["PX_LAST"].copy()
    px["date"] = pd.to_datetime(px["date"])
    last_date = px["date"].max()
    tickers_bb = [c for c in px.columns if c != "date"]
    print(f"PX_LAST: rows={len(px)}, last={last_date.date()}, tickers={len(tickers_bb)}")

    start = (last_date + timedelta(days=1)).date()
    end = date.today() + timedelta(days=1)  # yfinance end is exclusive
    if start >= end:
        print(f"already current (start={start} >= end={end})")
        return 0
    print(f"fetching {start} .. {end - timedelta(days=1)}")

    yahoo_to_bb = {}
    yahoo_tickers = []
    for bb in tickers_bb:
        y = bb_to_yahoo(bb)
        yahoo_to_bb[y] = bb
        yahoo_tickers.append(y)

    print(f"yfinance batch download (n={len(yahoo_tickers)}) ...")
    data = yf.download(
        yahoo_tickers,
        start=start,
        end=end,
        progress=False,
        group_by="column",
        auto_adjust=False,
        threads=True,
    )
    print(f"raw shape: {data.shape}")

    if isinstance(data.columns, pd.MultiIndex):
        closes = data["Close"]
    else:
        closes = pd.DataFrame({yahoo_tickers[0]: data["Close"]})
    closes.columns = [yahoo_to_bb.get(y, y) for y in closes.columns]
    closes = closes.reindex(columns=tickers_bb)
    closes.index = pd.to_datetime(closes.index)

    closes = closes.dropna(how="all").reset_index().rename(
        columns={"index": "date", "Date": "date"}
    )

    closes = closes[~closes["date"].isin(px["date"])]
    print(f"new rows after dedup: {len(closes)}")
    if closes.empty:
        print("nothing to append")
        return 0
    print(closes[["date"] + tickers_bb[:3]].head().to_string())

    updated = pd.concat([px, closes], ignore_index=True)
    updated["date"] = pd.to_datetime(updated["date"])
    updated = (
        updated.sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    print(f"updated PX_LAST: rows={len(updated)} (was {len(px)})")
    all_sheets["PX_LAST"] = updated

    print("writing workbook ...")
    with pd.ExcelWriter(PATH, engine="openpyxl", mode="w") as w:
        for name, df in all_sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    print(f"wrote {PATH}")

    re = pd.read_excel(PATH, sheet_name="PX_LAST", engine="openpyxl")
    re["date"] = pd.to_datetime(re["date"])
    print(f"verify: rows={len(re)}, last_date={re['date'].max().date()}")
    last_row = re[re["date"] == re["date"].max()].iloc[0]
    for t in ("GOOGL US Equity", "NVDA US Equity", "MSFT US Equity"):
        if t in re.columns:
            d = last_row["date"].date()
            v = last_row[t]
            print(f"  {t}: {v} on {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
