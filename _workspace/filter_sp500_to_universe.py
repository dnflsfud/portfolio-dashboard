"""Filter S&P500_filtered.xlsx down to the Universe.Ticker watchlist.

Reads Self_Port.xlsx → Universe.Ticker (9 tickers) and rewrites every wide
panel (PX_LAST, BEST_EPS, BEST_SALES, ...) to keep only those columns.

For PX_LAST, any Universe ticker that's NOT already in the file gets pulled
from Yahoo Finance (full history). For the consensus-estimate sheets
(BEST_EPS, BEST_SALES, etc.), Yahoo has no equivalent — missing tickers
just get omitted with a warning.

Run:
  python _workspace/filter_sp500_to_universe.py
"""
from __future__ import annotations

import shutil
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
SP500_PATH = ROOT / "data" / "S&P500_filtered.xlsx"
SELF_PORT_PATH = Path(
    r"C:\Users\westl\PycharmProjects\pythonProject\venv_vf_new\port\Self_Port.xlsx"
)


def bb_to_yahoo(t: str) -> str:
    return t.split()[0].replace("/", "-").upper()


def universe_tickers() -> List[str]:
    df = pd.read_excel(SELF_PORT_PATH, sheet_name="Universe", engine="openpyxl")
    return [t for t in df["Ticker"].dropna().astype(str).str.strip().tolist() if t and t.lower() != "nan"]


def yahoo_history(yahoo_ticker: str, start: date, end: date) -> pd.Series:
    """Daily close history. Returns empty Series on failure."""
    try:
        h = yf.Ticker(yahoo_ticker).history(
            start=start, end=end, interval="1d", auto_adjust=False, actions=False
        )
    except Exception as e:
        print(f"  yf {yahoo_ticker}: {e}")
        return pd.Series(dtype=float)
    if h.empty or "Close" not in h.columns:
        return pd.Series(dtype=float)
    s = h["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None) if s.index.tz is not None else pd.to_datetime(s.index)
    return s


def main() -> int:
    if not SP500_PATH.exists():
        print(f"missing: {SP500_PATH}")
        return 1

    targets = universe_tickers()
    print(f"target Universe.Ticker ({len(targets)}): {targets}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = SP500_PATH.with_suffix(f".prefilter-{ts}.xlsx")
    shutil.copy(SP500_PATH, backup)
    print(f"backup -> {backup.name}")

    print("reading all sheets ...")
    all_sheets = pd.read_excel(SP500_PATH, sheet_name=None, engine="openpyxl")
    print(f"sheets: {list(all_sheets.keys())}")

    # Master date range from PX_LAST (after recent yfinance update).
    px_master = all_sheets["PX_LAST"].copy()
    px_master["date"] = pd.to_datetime(px_master["date"])
    master_dates = px_master["date"].sort_values().unique()
    px_start = pd.Timestamp(master_dates.min()).date()
    px_end = pd.Timestamp(master_dates.max()).date() + timedelta(days=1)
    print(f"PX_LAST date range: {px_start} .. {pd.Timestamp(master_dates.max()).date()}")

    # 1) Filter every wide panel.
    summary = []
    for name, df in list(all_sheets.items()):
        if name == "SPX Index":
            print(f"  {name}: long-format calendar, kept as-is ({len(df)} rows)")
            summary.append((name, len(df.columns), len(df.columns), 0))
            continue
        if "date" not in df.columns:
            print(f"  {name}: skipped (no 'date' column)")
            continue
        original_cols = [c for c in df.columns if c != "date"]
        keep = [t for t in targets if t in original_cols]
        missing_in_panel = [t for t in targets if t not in original_cols]
        new_df = df[["date"] + keep].copy()
        all_sheets[name] = new_df
        summary.append((name, len(original_cols), len(keep), len(missing_in_panel)))
        print(f"  {name}: {len(original_cols)} -> {len(keep)}  (missing: {missing_in_panel})")

    # 2) For PX_LAST only, fetch Yahoo history for missing Universe tickers.
    px = all_sheets["PX_LAST"].copy()
    px["date"] = pd.to_datetime(px["date"])
    px = px.set_index("date").sort_index()
    have = set(px.columns)
    missing = [t for t in targets if t not in have]
    if missing:
        print(f"\nfetching Yahoo history for missing PX_LAST tickers: {missing}")
        for bb in missing:
            y = bb_to_yahoo(bb)
            print(f"  {bb} -> yahoo:{y} ...")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                s = yahoo_history(y, px_start, px_end)
            if s.empty:
                print(f"    no data, leaving column missing")
                continue
            s.name = bb
            px = px.join(s.to_frame(), how="outer")
            print(f"    inserted {s.notna().sum()} non-NaN values")
        px = px.sort_index()

    # Re-order PX_LAST columns to match Universe order; drop any extras.
    final_cols = [t for t in targets if t in px.columns]
    px = px.reindex(columns=final_cols)
    px = px.reset_index().rename(columns={"index": "date", "Date": "date"})
    all_sheets["PX_LAST"] = px

    # 3) Re-order other panels too (Universe-order).
    for name, df in all_sheets.items():
        if name in ("PX_LAST", "SPX Index") or "date" not in df.columns:
            continue
        keep = [t for t in targets if t in df.columns]
        all_sheets[name] = df[["date"] + keep]

    # 4) Write back.
    print(f"\nwriting filtered workbook ({len(all_sheets)} sheets) ...")
    with pd.ExcelWriter(SP500_PATH, engine="openpyxl", mode="w") as w:
        for name, df in all_sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    size_mb = SP500_PATH.stat().st_size / (1024 * 1024)
    print(f"wrote {SP500_PATH} ({size_mb:.1f} MB)")

    # 5) Verify.
    print("\nverification:")
    re_xl = pd.ExcelFile(SP500_PATH, engine="openpyxl")
    for sheet in re_xl.sheet_names:
        df = pd.read_excel(re_xl, sheet, nrows=1)
        cols = [c for c in df.columns if c != "date" and c != "Ticker"]
        print(f"  {sheet}: {len(df.columns)} cols, tickers={cols}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
