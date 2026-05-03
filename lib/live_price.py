"""Yahoo Finance live-price fallback when PX_LAST is stale.

PX_LAST is sourced from S&P500_filtered.xlsx and only refreshes when the
user re-exports their Bloomberg dump. If the latest entry in the holdings
sheet is newer than the last PX_LAST row — or if PX_LAST hasn't been
updated to the latest business day — we fetch the latest close from
Yahoo Finance instead.

Bloomberg → Yahoo ticker conversion: take the first whitespace-delimited
token (e.g. ``AAPL US Equity`` → ``AAPL``). Class-share suffixes like
``BRK/B US Equity`` get normalised by replacing ``/`` with ``-`` (Yahoo
convention: ``BRK-B``).
"""
from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd
import streamlit as st

try:
    import yfinance as _yf
    _YF_AVAILABLE = True
except ImportError:  # pragma: no cover
    _yf = None  # type: ignore
    _YF_AVAILABLE = False


def bloomberg_to_yahoo(ticker: str) -> str:
    """Convert ``'AAPL US Equity'`` to ``'AAPL'``; ``'BRK/B US Equity'`` to ``'BRK-B'``."""
    if not ticker:
        return ""
    head = ticker.split()[0]
    return head.replace("/", "-").upper()


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_yahoo_latest_cached(yahoo_ticker: str) -> Tuple[Optional[float], Optional[pd.Timestamp]]:
    """Cache the Yahoo response for 5 minutes per ticker."""
    if not _YF_AVAILABLE or not yahoo_ticker:
        return None, None
    try:
        t = _yf.Ticker(yahoo_ticker)
        try:
            price = t.fast_info.get("last_price")  # type: ignore[attr-defined]
        except Exception:
            price = None
        if price is not None and not pd.isna(price):
            return float(price), pd.Timestamp.utcnow().normalize()
        hist = t.history(period="5d", interval="1d")
        if hist.empty:
            return None, None
        return float(hist["Close"].iloc[-1]), pd.Timestamp(hist.index[-1])
    except Exception:
        return None, None


def fetch_yahoo_latest(bloomberg_ticker: str) -> Tuple[Optional[float], Optional[pd.Timestamp]]:
    """Public wrapper: returns (price, asof_date) or (None, None)."""
    return _fetch_yahoo_latest_cached(bloomberg_to_yahoo(bloomberg_ticker))


def yfinance_available() -> bool:
    return _YF_AVAILABLE
