"""Business-day calendar utilities anchored on the SPX Index sheet."""
from __future__ import annotations

import pandas as pd

from .data_loader import load_spx_index, load_px_last


def get_business_calendar() -> pd.DatetimeIndex:
    """Master business-day calendar.

    Anchored on the SPX Index 'date' column, but extended forward with the
    PX_LAST trading days that come after the SPX Index sheet's last date.
    The SPX Index sheet is only rebuilt by the full Bloomberg sync, whereas
    PX_LAST is refreshed every day (yfinance), so without this extension the
    calendar lags behind the latest prices and downstream views (e.g. the
    monthly daily-return table) silently drop the most recent month.
    Weekday filter drops weekend rows that can sneak into PX_LAST.
    """
    spx = load_spx_index()
    if "date" in spx.columns:
        dates = pd.to_datetime(spx["date"])
    else:
        dates = pd.to_datetime(spx.index)
    cal = pd.DatetimeIndex(pd.Series(dates).dropna()).normalize().unique()

    try:
        px = load_px_last()
    except Exception:
        return cal.sort_values()
    if len(px.index):
        px_dates = pd.DatetimeIndex(pd.to_datetime(px.index)).normalize()
        extra = px_dates[px_dates.weekday < 5]
        if len(cal):
            extra = extra[extra > cal.max()]
        if len(extra):
            cal = cal.append(extra)
    return cal.normalize().unique().sort_values()


def reindex_to_business_days(
    df: pd.DataFrame,
    calendar: pd.DatetimeIndex | None = None,
    *,
    ffill: bool = True,
) -> pd.DataFrame:
    """Align a date-indexed DataFrame onto the business-day calendar.

    Forward-fills gaps by default so weekly/monthly Bloomberg estimates land
    on every trading day.
    """
    if calendar is None:
        calendar = get_business_calendar()
    df = df.sort_index()
    out = df.reindex(calendar)
    if ffill:
        out = out.ffill()
    return out


def last_n_years(df: pd.DataFrame, years: int = 3, trading_days_per_year: int = 252) -> pd.DataFrame:
    """Return the last `years * 252` rows of a business-day-indexed frame."""
    n = years * trading_days_per_year
    if len(df) <= n:
        return df
    return df.iloc[-n:]
