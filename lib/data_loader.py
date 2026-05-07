"""Data loaders for the Self_Port Streamlit app's new tabs.

Loads:
  - Self_Port.xlsx Sheet2  (daughter's portfolio holdings)
  - Self_Port.xlsx Universe.Ticker_Arin  (stock universe)
  - S&P500_filtered.xlsx  (BEST_EPS / BEST_SALES / PX_LAST / SPX Index)

Path resolution:
  Tries BASE_DIR/<name>.xlsx first, then BASE_DIR/data/<name>.xlsx.
  This way the loader works whether the app runs from port/ or from a
  worktree where Self_Port.xlsx is only in data/.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent

def _ancestors(start: Path, depth: int = 5) -> List[Path]:
    out = [start]
    cur = start
    for _ in range(depth):
        if cur.parent == cur:
            break
        cur = cur.parent
        out.append(cur)
    return out


_ANCESTORS = _ancestors(BASE_DIR, depth=5)

SELF_PORT_CANDIDATES = [
    *(d / "Self_Port.xlsx" for d in _ANCESTORS),
    *(d / "data" / "Self_Port.xlsx" for d in _ANCESTORS),
]
SP500_CANDIDATES = [
    *(d / "data" / "S&P500_filtered.xlsx" for d in _ANCESTORS),
    *(d / "S&P500_filtered.xlsx" for d in _ANCESTORS),
    *(d / "S&P500.xlsx" for d in _ANCESTORS),
]


def _resolve_self_port_path() -> Path:
    """Pick the Self_Port.xlsx that actually has Sheet2 and Universe."""
    for c in SELF_PORT_CANDIDATES:
        if not c.exists():
            continue
        try:
            sheets = pd.ExcelFile(c, engine="openpyxl").sheet_names
        except Exception:
            continue
        if "Sheet2" in sheets and "Universe" in sheets:
            return c
    fallback = next((c for c in SELF_PORT_CANDIDATES if c.exists()), None)
    if fallback is not None:
        return fallback
    raise FileNotFoundError(
        "Self_Port.xlsx not found in any of: "
        + ", ".join(str(c) for c in SELF_PORT_CANDIDATES)
    )


def _resolve_sp500_path() -> Path:
    for c in SP500_CANDIDATES:
        if c.exists():
            return c
    raise FileNotFoundError(
        "S&P500 file not found in any of: "
        + ", ".join(str(c) for c in SP500_CANDIDATES)
    )


def _mtime(p: Path) -> float:
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def _read_sheet(path_str: str, sheet: str, cache_key: float) -> pd.DataFrame:
    """Read one sheet. The cache_key argument forces invalidation on file change."""
    return pd.read_excel(path_str, sheet_name=sheet, engine="openpyxl")


def load_self_port_holdings() -> pd.DataFrame:
    """Load Self_Port.xlsx Sheet2 (daughter's holdings).

    Returns a DataFrame with columns:
      Date (datetime), Ticker (str), Number (int), Entry_Price (float), Price (float|NaN)
    """
    path = _resolve_self_port_path()
    df = _read_sheet(str(path), "Sheet2", _mtime(path)).copy()
    if df.empty:
        return df
    df["Date"] = pd.to_datetime(df["Date"])
    df["Ticker"] = df["Ticker"].astype(str).str.strip()
    df["Entry_Price"] = pd.to_numeric(df["Entry_Price"], errors="coerce")
    if "Number" in df.columns:
        df["Number"] = pd.to_numeric(df["Number"], errors="coerce").fillna(0).astype(int)
    return df.reset_index(drop=True)


def load_universe_tickers() -> List[str]:
    """Load the Ticker_Arin column from the Universe sheet, dropping NaN."""
    path = _resolve_self_port_path()
    df = _read_sheet(str(path), "Universe", _mtime(path))
    if "Ticker_Arin" not in df.columns:
        return []
    series = df["Ticker_Arin"].dropna().astype(str).str.strip()
    return [t for t in series.tolist() if t and t.lower() != "nan"]


@st.cache_data(show_spinner=False)
def _read_panel(path_str: str, sheet: str, cache_key: float) -> pd.DataFrame:
    df = pd.read_excel(path_str, sheet_name=sheet, engine="openpyxl")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
    return df


def load_sp500_panel(metric: str) -> pd.DataFrame:
    """Load one sheet from S&P500_filtered.xlsx as a date-indexed panel.

    Args:
      metric: one of {'BEST_EPS', 'BEST_SALES', 'PX_LAST', 'BEST_PE_RATIO', ...}.

    Returns a DataFrame with a DatetimeIndex and Bloomberg ticker columns
    (e.g. 'AAPL US Equity'). For sheets that are not panel-shaped (e.g.
    'SPX Index' which is long format), returns the raw read.
    """
    path = _resolve_sp500_path()
    return _read_panel(str(path), metric, _mtime(path))


def load_spx_index() -> pd.DataFrame:
    """Load the SPX Index sheet (long format: date, Ticker, SPX Index).

    Tries the bundled S&P500_filtered.xlsx first (contains an 'SPX Index'
    sheet), then falls back to a separate Index.xlsx if available.
    """
    path = _resolve_sp500_path()
    try:
        return _read_panel(str(path), "SPX Index", _mtime(path))
    except (ValueError, KeyError):
        candidates = []
        for d in _ANCESTORS:
            candidates.append(d / "data" / "Index.xlsx")
            candidates.append(d / "Index.xlsx")
        for c in candidates:
            if c.exists():
                return _read_panel(str(c), "SPX Index", _mtime(c))
        raise


def load_px_last() -> pd.DataFrame:
    """Convenience: PX_LAST panel for current-price lookup."""
    return load_sp500_panel("PX_LAST")


def load_usdkrw() -> pd.Series:
    """USD/KRW exchange rate as a Series indexed by business-day date.

    Reads the 'USDKRW Curncy' sheet (long-format: [date, Ticker, USDKRW Curncy])
    from S&P500_filtered.xlsx. Returns an empty Series if the sheet is missing
    so callers can degrade gracefully (no FX conversion).
    """
    path = _resolve_sp500_path()
    try:
        df = _read_panel(str(path), "USDKRW Curncy", _mtime(path))
    except (ValueError, KeyError):
        return pd.Series(dtype=float, name="USDKRW")

    if "date" in df.columns and "USDKRW Curncy" in df.columns:
        s = df.set_index(pd.to_datetime(df["date"]))["USDKRW Curncy"]
    elif "USDKRW Curncy" in df.columns:
        s = df["USDKRW Curncy"]
    else:
        return pd.Series(dtype=float, name="USDKRW")
    s = pd.to_numeric(s, errors="coerce").dropna().sort_index()
    s.name = "USDKRW"
    return s


def get_data_paths() -> dict:
    """Resolved paths for diagnostics."""
    out = {}
    try:
        out["self_port"] = str(_resolve_self_port_path())
    except FileNotFoundError as e:
        out["self_port"] = f"ERROR: {e}"
    try:
        out["sp500"] = str(_resolve_sp500_path())
    except FileNotFoundError as e:
        out["sp500"] = f"ERROR: {e}"
    return out
