"""Rebuild port/data/S&P500_filtered.xlsx from the master Bloomberg dumps.

Sources
-------
  primary  : C:/Users/westl/PycharmProjects/pythonProject/S&P500.xlsx
  index    : C:/Users/westl/PycharmProjects/pythonProject/Index.xlsx
  watchlist: <repo>/Self_Port.xlsx → Universe.Ticker  (9 tickers)
  fallback : Yahoo Finance (PX_LAST only — for tickers absent from both
             master files; consensus sheets cannot be reconstructed)

Output
------
  <repo>/data/S&P500_filtered.xlsx   (overwritten, with timestamped backup)

Behaviour per sheet
-------------------
  Wide panels (date + ticker columns):
      - Start from S&P500.xlsx columns ∩ Universe.Ticker
      - For Universe tickers missing from S&P500.xlsx, look up in Index.xlsx
        and merge in (date-aligned outer join)
      - For PX_LAST only: any Universe ticker still missing is pulled from
        Yahoo (full daily history)
  SPX Index           : taken verbatim from Index.xlsx
  Earnings_Date       : taken from S&P500.xlsx (filtered to Universe.Ticker
                        subset) if present
  Other special sheets: passed through if relevant

Run
---
  python _workspace/sync_filtered_from_masters.py
"""
from __future__ import annotations

import shutil
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

# --------------------------------------------------------------------------- #
# Paths                                                                       #
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent  # repo root (worktree)
SP500_MASTER = Path(r"C:\Users\westl\PycharmProjects\pythonProject\S&P500.xlsx")
INDEX_MASTER = Path(r"C:\Users\westl\PycharmProjects\pythonProject\Index.xlsx")
SELF_PORT = Path(r"C:\Users\westl\PycharmProjects\pythonProject\venv_vf_new\port\Self_Port.xlsx")
OUTPUT = ROOT / "data" / "S&P500_filtered.xlsx"

# Sheets to filter and write into the output (order matters — first existing wins).
WIDE_PANEL_SHEETS = [
    "PX_LAST",
    "BEST_EPS", "BEST_SALES",
    "BEST_PE_RATIO", "BEST_PEG_RATIO",
    "BEST_CALCULATED_FCF", "BEST_GROSS_MARGIN",
    "CUR_MKT_CAP", "OPER_MARGIN",
    "BEST_CAPEX", "BEST_ROE",
    "BEST_PX_BPS_RATIO", "BEST_EV_TO_BEST_EBITDA",
    "NEWS_SENTIMENT_DAILY_AVG", "EQY_REC_CONS",
    "SHORT_INT_RATIO",
]
SPECIAL_SHEETS = ["SPX Index", "Earnings_Date"]

# Proxy fill for ETF/illiquid tickers that lack Bloomberg consensus.
# Used ONLY for the estimate sheets listed in PROXY_SHEETS — applied AFTER
# the primary+secondary merge, ONLY when the target column is missing or
# entirely NaN (so any real Bloomberg data wins).
#
# value type: list of (source_file_key, source_ticker) — when multiple sources
# are given, the proxy is the date-aligned MEAN across them (good for sector
# / industry baskets like DRAM = Samsung + SK Hynix + Micron).
PROXY_SHEETS = {"BEST_EPS", "BEST_SALES"}
PROXY_MAP: Dict[str, List[Tuple[str, str]]] = {
    "SPY US Equity":  [("index", "SPX Index")],
    "QQQ US Equity":  [("index", "NDX Index")],
    "BAI US Equity":  [("index", "BAI Index")],
    # NOTE: DRAM is no longer proxied. Samsung (005930 KS), SK Hynix
    # (000660 KS) and Micron (MU US) are now first-class entries in
    # Universe.Ticker_Arin and use their own raw Bloomberg consensus
    # series — no normalization, just native growth rates.
}


# --------------------------------------------------------------------------- #
# Small helpers                                                               #
# --------------------------------------------------------------------------- #
def _read_all_sheets(path: Path) -> Dict[str, pd.DataFrame]:
    if not path.exists():
        print(f"  ! missing: {path}")
        return {}
    print(f"  reading {path.name} ...")
    return pd.read_excel(path, sheet_name=None, engine="openpyxl")


def _normalize_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Make sure date is a real datetime and is the first column."""
    if "date" not in df.columns:
        return df
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    cols = ["date"] + [c for c in d.columns if c != "date"]
    return d[cols].sort_values("date").reset_index(drop=True)


def _bb_to_yahoo(t: str) -> str:
    return t.split()[0].replace("/", "-").upper()


def _universe_tickers() -> List[str]:
    df = pd.read_excel(SELF_PORT, sheet_name="Universe", engine="openpyxl")
    return [t for t in df["Ticker"].dropna().astype(str).str.strip().tolist()
            if t and t.lower() != "nan"]


# --------------------------------------------------------------------------- #
# Per-sheet merge logic                                                       #
# --------------------------------------------------------------------------- #
def _filter_panel(
    panel: Optional[pd.DataFrame],
    targets: List[str],
) -> pd.DataFrame:
    if panel is None or panel.empty or "date" not in panel.columns:
        return pd.DataFrame()
    keep = [t for t in targets if t in panel.columns]
    return panel[["date"] + keep].copy() if keep else pd.DataFrame({"date": panel["date"]})


def _merge_panels(primary: pd.DataFrame, secondary: pd.DataFrame, targets: List[str]) -> pd.DataFrame:
    """Left-join secondary's missing target columns onto primary by date."""
    if primary.empty:
        return secondary.copy() if not secondary.empty else pd.DataFrame()
    if secondary.empty:
        return primary

    primary = primary.copy()
    secondary = secondary.copy()
    primary["date"] = pd.to_datetime(primary["date"])
    secondary["date"] = pd.to_datetime(secondary["date"])

    have = set(primary.columns) - {"date"}
    want_from_sec = [t for t in targets if t in secondary.columns and t not in have]
    if not want_from_sec:
        return primary

    # Outer-join on date so we don't lose rows the secondary covers.
    merged = pd.merge(
        primary, secondary[["date"] + want_from_sec],
        on="date", how="outer",
    ).sort_values("date").reset_index(drop=True)
    return merged


def _yahoo_series(yticker: str, start: date, end: date) -> pd.Series:
    try:
        h = yf.Ticker(yticker).history(
            start=start, end=end, interval="1d",
            auto_adjust=False, actions=False,
        )
    except Exception as e:
        print(f"      yahoo {yticker}: {e}")
        return pd.Series(dtype=float)
    if h.empty or "Close" not in h.columns:
        return pd.Series(dtype=float)
    s = h["Close"].copy()
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s


def _apply_proxies(
    merged: pd.DataFrame,
    sheet_name: str,
    sp_dict: Dict[str, pd.DataFrame],
    ix_dict: Dict[str, pd.DataFrame],
    targets: List[str],
) -> pd.DataFrame:
    """Fill missing target columns by averaging proxy series from masters.

    Only operates on sheets in PROXY_SHEETS, only writes if the target
    column is absent or entirely NaN — never overwrites real consensus.

    Multi-source proxies (e.g. DRAM = Samsung + SK Hynix + Micron) use
    **first-value normalization before averaging** so currency / scale
    differences between sources (KRW vs USD, index level vs per-share)
    don't bias the resulting momentum. The proxy column is rescaled back
    to the first source's first value so absolute numbers stay readable.
    """
    if sheet_name not in PROXY_SHEETS or merged.empty:
        return merged
    src_dicts = {"sp500": sp_dict, "index": ix_dict}
    out = merged.copy()
    out["date"] = pd.to_datetime(out["date"])
    out_idx = out.set_index("date")

    for target, sources in PROXY_MAP.items():
        if target not in targets:
            continue
        if target in out_idx.columns and out_idx[target].notna().any():
            print(f"      proxy SKIP  {target} ({sheet_name}): real data present")
            continue

        series_list: List[pd.Series] = []
        used: List[str] = []
        for file_key, src_ticker in sources:
            d = src_dicts.get(file_key, {})
            if sheet_name not in d:
                continue
            df = d[sheet_name].copy()
            if "date" not in df.columns or src_ticker not in df.columns:
                continue
            df["date"] = pd.to_datetime(df["date"])
            s = pd.to_numeric(df.set_index("date")[src_ticker], errors="coerce")
            if s.notna().any():
                series_list.append(s)
                used.append(f"{file_key}:{src_ticker}")

        if not series_list:
            print(f"      proxy MISS  {target} ({sheet_name}): no source data found")
            continue

        if len(series_list) == 1:
            proxy = series_list[0].copy()
            kind = "1:1"
        else:
            # Normalize each source by its first non-NaN value (= rebased to 1.0
            # at its earliest date), then take the date-aligned mean.
            normalized: List[pd.Series] = []
            for s in series_list:
                fvi = s.first_valid_index()
                base = s.loc[fvi] if fvi is not None else None
                if base is None or pd.isna(base) or base == 0:
                    continue
                normalized.append(s / base)
            if not normalized:
                continue
            mean_norm = pd.concat(normalized, axis=1).mean(axis=1, skipna=True)
            # Rescale the index proxy to the first source's first value so the
            # column has comparable magnitude to neighboring tickers.
            anchor = series_list[0].dropna()
            scale = anchor.iloc[0] if not anchor.empty else 1.0
            proxy = mean_norm * scale
            kind = f"NORMED-MEAN×{scale:.2f}"

        all_dates = out_idx.index.union(proxy.index)
        out_idx = out_idx.reindex(all_dates)
        out_idx[target] = proxy.reindex(all_dates)
        print(f"      proxy FILL  {target} ({sheet_name}) <- {kind}({', '.join(used)})  "
              f"{out_idx[target].notna().sum()} non-NaN")

    return out_idx.sort_index().reset_index().rename(columns={"index": "date"})


def _augment_px_last_with_yahoo(
    px: pd.DataFrame,
    targets: List[str],
) -> pd.DataFrame:
    """For Universe tickers still missing from PX_LAST, fetch from Yahoo."""
    if px.empty:
        return px
    have = set(px.columns) - {"date"}
    missing = [t for t in targets if t not in have]
    if not missing:
        return px
    print(f"    fetching Yahoo PX for: {missing}")
    px = px.copy()
    px["date"] = pd.to_datetime(px["date"])
    px = px.set_index("date").sort_index()

    # Hist range = full PX_LAST coverage so charts work going back too
    start = px.index.min().date()
    end = (px.index.max().date() + timedelta(days=1))
    if pd.Timestamp.today().date() > end - timedelta(days=1):
        end = pd.Timestamp.today().date() + timedelta(days=1)

    for bb in missing:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s = _yahoo_series(_bb_to_yahoo(bb), start, end)
        if s.empty:
            print(f"      {bb}: no data, leaving missing")
            continue
        s.name = bb
        px = px.join(s.to_frame(), how="outer")
        print(f"      {bb}: {s.notna().sum()} non-NaN points")
    return px.reset_index().rename(columns={"index": "date", "Date": "date"})


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def main() -> int:
    if not SP500_MASTER.exists() and not INDEX_MASTER.exists():
        print("FATAL: neither master file exists, aborting")
        return 1
    if not SELF_PORT.exists():
        print(f"FATAL: Self_Port.xlsx not found at {SELF_PORT}")
        return 1

    targets = _universe_tickers()
    print(f"Universe.Ticker ({len(targets)}): {targets}")

    if OUTPUT.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = OUTPUT.with_suffix(f".sync-backup-{ts}.xlsx")
        shutil.copy(OUTPUT, backup)
        print(f"backup -> {backup.name}")

    print()
    print("--- reading masters ---")
    sp = _read_all_sheets(SP500_MASTER)
    ix = _read_all_sheets(INDEX_MASTER)
    print()
    print(f"S&P500 sheets: {len(sp)}    Index sheets: {len(ix)}")

    out_sheets: Dict[str, pd.DataFrame] = {}

    print()
    print("--- merging wide panels ---")
    for sheet in WIDE_PANEL_SHEETS:
        prim = _normalize_panel(sp[sheet]) if sheet in sp else pd.DataFrame()
        sec = _normalize_panel(ix[sheet]) if sheet in ix else pd.DataFrame()
        prim_f = _filter_panel(prim, targets)
        sec_f = _filter_panel(sec, targets)
        merged = _merge_panels(prim_f, sec_f, targets)

        if sheet == "PX_LAST":
            merged = _augment_px_last_with_yahoo(merged, targets)

        # Proxy fill for BEST_EPS / BEST_SALES (SPY→SPX, QQQ→NDX, etc.)
        if sheet in PROXY_SHEETS:
            merged = _apply_proxies(merged, sheet, sp, ix, targets)

        # Re-order: date + Universe.Ticker order, drop unrequested
        if not merged.empty:
            kept = [t for t in targets if t in merged.columns]
            merged = merged[["date"] + kept]
            merged["date"] = pd.to_datetime(merged["date"])
            merged = merged.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)

        cols = [c for c in merged.columns if c != "date"]
        print(f"  {sheet:30s}  cols={len(cols)}  rows={len(merged)}  -> {cols}")
        if not merged.empty:
            out_sheets[sheet] = merged

    print()
    print("--- special sheets ---")

    # SPX Index — prefer Index.xlsx version (master calendar)
    spx = ix.get("SPX Index", sp.get("SPX Index"))
    if spx is not None:
        spx = spx.copy()
        if "date" in spx.columns:
            spx["date"] = pd.to_datetime(spx["date"])
            spx = spx.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        out_sheets["SPX Index"] = spx
        print(f"  SPX Index                    rows={len(spx)}")

    # Earnings_Date — only from S&P500.xlsx (date + Universe.Ticker subset)
    if "Earnings_Date" in sp:
        ed = _normalize_panel(sp["Earnings_Date"])
        kept = [t for t in targets if t in ed.columns]
        if kept:
            ed = ed[["date"] + kept]
            out_sheets["Earnings_Date"] = ed
            print(f"  Earnings_Date                cols={len(kept)}  rows={len(ed)}")

    if not out_sheets:
        print("FATAL: no sheets produced, aborting (output not modified)")
        return 1

    print()
    print(f"--- writing {OUTPUT} ({len(out_sheets)} sheets) ---")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUTPUT, engine="openpyxl", mode="w") as w:
        for name, df in out_sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"wrote {OUTPUT.name}   {size_mb:.2f} MB")

    # Verification readback
    print()
    print("--- verification ---")
    re_xl = pd.ExcelFile(OUTPUT, engine="openpyxl")
    for s in re_xl.sheet_names:
        df = pd.read_excel(re_xl, s, nrows=2, engine="openpyxl")
        cols = [c for c in df.columns if c not in ("date", "Ticker")]
        print(f"  {s:30s} cols={len(df.columns)} ({cols if len(cols) < 12 else str(len(cols))+' tickers'})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
