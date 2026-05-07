"""Business-day calendar utilities anchored on the SPX Index sheet."""
from __future__ import annotations

import pandas as pd

from .data_loader import load_spx_index


def get_business_calendar() -> pd.DatetimeIndex:
    """The SPX Index 'date' column is the master business-day calendar."""
    spx = load_spx_index()
    if "date" in spx.columns:
        dates = pd.to_datetime(spx["date"]).sort_values().unique()
    else:
        dates = pd.to_datetime(spx.index).sort_values().unique()
    return pd.DatetimeIndex(dates)


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
