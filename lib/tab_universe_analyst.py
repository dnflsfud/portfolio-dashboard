"""Universe analyst tab — estimate-momentum charts and trajectory scatter.

Structure (per request):

Tab "3개월" / Tab "12개월"
  ├─ Forward EPS  [N]M growth-rate time-series   (last 3 years)
  ├─ Forward Sales [N]M growth-rate time-series  (last 3 years)
  ├─ Trajectory scatter:
  │     x = Fwd EPS  [N]M growth (%)
  │     y = Fwd Sales [N]M growth (%)
  │     For each ticker, 4 points at as-of dates  3M ago / 1M ago / 2W ago / Now,
  │     connected by arrows showing the path.
  └─ Snapshot table  (Now values, plus the 4-period trajectory per ticker)

Momentum formula (user-confirmed):
  panel[t] / panel[t - N business days] - 1
  where N = 63 (3M tab)  or  252 (12M tab).
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .data_loader import load_universe_tickers, load_sp500_panel
from .calendar_utils import get_business_calendar, reindex_to_business_days, last_n_years

LOOKBACK_3M = 63
LOOKBACK_12M = 252
TIMELINE_YEARS = 3

# As-of offsets in trading days (matches the existing app's PERIODS).
TRAJECTORY_PERIODS: List[Tuple[str, int]] = [
    ("3M ago", 63),
    ("1M ago", 21),
    ("2W ago", 10),
    ("Now", 0),
]
PERIOD_COLORS: Dict[str, str] = {
    "Now": "#1f77b4",      # blue
    "2W ago": "#9467bd",   # purple
    "1M ago": "#ff7f0e",   # orange
    "3M ago": "#d62728",   # red
}


# --------------------------------------------------------------------------- #
# Core math helpers                                                           #
# --------------------------------------------------------------------------- #
def _compute_momentum(panel: pd.DataFrame, periods: int) -> pd.DataFrame:
    """panel[t] / panel[t - periods] - 1, element-wise.  First `periods` rows -> NaN."""
    return panel / panel.shift(periods) - 1.0


def _latest_momentum(panel: pd.DataFrame, periods: int) -> pd.Series:
    mom = _compute_momentum(panel, periods)
    return mom.iloc[-1] if len(mom) else pd.Series(dtype=float)


def _aligned_panel(metric: str) -> pd.DataFrame:
    panel = load_sp500_panel(metric)
    return reindex_to_business_days(panel, get_business_calendar(), ffill=True)


def _filter_universe(universe: List[str], available: pd.Index) -> Tuple[List[str], List[str]]:
    in_panel = [t for t in universe if t in available]
    missing = [t for t in universe if t not in available]
    return in_panel, missing


# --------------------------------------------------------------------------- #
# Renderers                                                                   #
# --------------------------------------------------------------------------- #
def _render_momentum_timeseries(
    mom_recent: pd.DataFrame,
    selected: List[str],
    title: str,
) -> None:
    fig = go.Figure()
    plotted = 0
    for ticker in selected:
        if ticker not in mom_recent.columns:
            continue
        s = (mom_recent[ticker] * 100).dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=ticker,
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}%<extra>" + ticker + "</extra>",
        ))
        plotted += 1
    if plotted == 0:
        st.info(f"📭 {title}: 표시할 데이터가 없어요.")
        return
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4)
    fig.update_layout(
        title=title,
        xaxis_title="날짜",
        yaxis_title="상승률 (%)",
        height=380,
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.2),
    )
    st.plotly_chart(fig, width="stretch")


def _trajectory_points(
    eps_mom: pd.DataFrame,
    sales_mom: pd.DataFrame,
    ticker: str,
) -> pd.DataFrame:
    """4 trajectory points for a ticker, ordered 3M ago -> 1M ago -> 2W ago -> Now."""
    rows = []
    n = len(eps_mom)
    for label, lag in TRAJECTORY_PERIODS:
        idx = n - 1 - lag
        if idx < 0:
            x = y = np.nan
        else:
            x = eps_mom.iloc[idx].get(ticker, np.nan)
            y = sales_mom.iloc[idx].get(ticker, np.nan)
        rows.append({
            "period": label, "lag": lag,
            "eps_pct": (x * 100) if pd.notna(x) else np.nan,
            "sales_pct": (y * 100) if pd.notna(y) else np.nan,
        })
    return pd.DataFrame(rows)


def _render_trajectory_scatter(
    eps_mom: pd.DataFrame,
    sales_mom: pd.DataFrame,
    selected: List[str],
    horizon_label: str,
) -> None:
    fig = go.Figure()

    # Period legend (a single dummy marker per period color, so the legend
    # explains what the dot colors mean even before any ticker is plotted).
    for p, c in PERIOD_COLORS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color=c, line=dict(color="black", width=0.5)),
            name=p, legendgroup="periods", showlegend=True,
        ))

    palette = px.colors.qualitative.Plotly + px.colors.qualitative.Dark24
    ticker_colors = {t: c for t, c in zip(selected, itertools.cycle(palette))}

    plotted = 0
    for ticker in selected:
        if ticker not in eps_mom.columns or ticker not in sales_mom.columns:
            continue
        traj = _trajectory_points(eps_mom, sales_mom, ticker)
        valid = traj.dropna(subset=["eps_pct", "sales_pct"])
        if valid.empty:
            continue

        ticker_c = ticker_colors[ticker]

        # Line + per-point colored markers
        fig.add_trace(go.Scatter(
            x=valid["eps_pct"].values,
            y=valid["sales_pct"].values,
            mode="lines+markers+text",
            text=["", "", "", ticker][-len(valid):],  # label only the last point
            textposition="top center",
            textfont=dict(size=12, color=ticker_c),
            line=dict(color=ticker_c, width=2),
            marker=dict(
                size=12,
                color=[PERIOD_COLORS[p] for p in valid["period"]],
                line=dict(color=ticker_c, width=1.5),
            ),
            name=ticker,
            legendgroup="tickers",
            customdata=valid["period"].values,
            hovertemplate=(
                "<b>" + ticker + "</b><br>"
                "%{customdata}<br>"
                "EPS " + horizon_label + ": %{x:+.2f}%<br>"
                "Sales " + horizon_label + ": %{y:+.2f}%<extra></extra>"
            ),
        ))

        # Arrows between consecutive valid segments (3M -> 1M -> 2W -> Now)
        xs = valid["eps_pct"].values
        ys = valid["sales_pct"].values
        for i in range(len(xs) - 1):
            fig.add_annotation(
                x=xs[i + 1], y=ys[i + 1],
                ax=xs[i], ay=ys[i],
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=3, arrowsize=1.4, arrowwidth=2.2,
                arrowcolor=ticker_c, opacity=0.85,
            )
        plotted += 1

    if plotted == 0:
        st.info(f"📭 {horizon_label} 궤적: 표시할 데이터가 없어요.")
        return

    fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.4)
    fig.add_vline(x=0, line_dash="dot", line_color="gray", opacity=0.4)
    fig.update_layout(
        title=f"📐 {horizon_label} 추정치 모멘텀 궤적  (3M ago → 1M ago → 2W ago → Now)",
        xaxis=dict(title=f"Fwd EPS {horizon_label} 상승률 (%)", tickformat=".1f"),
        yaxis=dict(title=f"Fwd Sales {horizon_label} 상승률 (%)", tickformat=".1f"),
        height=560,
        template="plotly_white",
        hovermode="closest",
        legend=dict(orientation="v", y=1, x=1.02),
    )
    st.plotly_chart(fig, width="stretch")


def _render_trajectory_table(
    eps_mom: pd.DataFrame,
    sales_mom: pd.DataFrame,
    selected: List[str],
    horizon_label: str,
) -> None:
    """One row per (ticker, period) showing EPS% and Sales% at each as-of."""
    rows = []
    for ticker in selected:
        if ticker not in eps_mom.columns or ticker not in sales_mom.columns:
            continue
        traj = _trajectory_points(eps_mom, sales_mom, ticker)
        for _, p in traj.iterrows():
            rows.append({
                "Ticker": ticker, "As-of": p["period"],
                f"EPS {horizon_label}": p["eps_pct"],
                f"Sales {horizon_label}": p["sales_pct"],
            })
    if not rows:
        return
    df = pd.DataFrame(rows)

    def fmt(v):
        return "—" if pd.isna(v) else f"{v:+.2f}%"

    st.subheader(f"📊 {horizon_label} 모멘텀 궤적 표")
    df_fmt = df.copy()
    df_fmt[f"EPS {horizon_label}"] = df_fmt[f"EPS {horizon_label}"].apply(fmt)
    df_fmt[f"Sales {horizon_label}"] = df_fmt[f"Sales {horizon_label}"].apply(fmt)
    st.dataframe(df_fmt, width="stretch", hide_index=True)


def _render_horizon_section(
    horizon_label: str,
    lookback: int,
    eps_panel: pd.DataFrame,
    sales_panel: pd.DataFrame,
    selected: List[str],
) -> None:
    """One horizon tab body."""
    eps_mom = _compute_momentum(eps_panel, lookback)
    sales_mom = _compute_momentum(sales_panel, lookback)
    eps_recent = last_n_years(eps_mom, TIMELINE_YEARS)
    sales_recent = last_n_years(sales_mom, TIMELINE_YEARS)

    _render_momentum_timeseries(
        eps_recent, selected,
        title=f"📈 Forward EPS {horizon_label} 상승률  (최근 {TIMELINE_YEARS}년)",
    )
    _render_momentum_timeseries(
        sales_recent, selected,
        title=f"💰 Forward Sales {horizon_label} 상승률  (최근 {TIMELINE_YEARS}년)",
    )
    _render_trajectory_scatter(eps_mom, sales_mom, selected, horizon_label)
    _render_trajectory_table(eps_mom, sales_mom, selected, horizon_label)


def render_universe_analyst_tab() -> None:
    """Public entry point."""
    st.header("🔍 유니버스 종목 분석 — 추정치 모멘텀")
    st.caption(
        "산식: BEST_EPS[t] / BEST_EPS[t − N영업일] − 1   "
        "(3M ⇒ N=63,  12M ⇒ N=252).   Sales도 동일."
    )

    universe = load_universe_tickers()
    if not universe:
        st.info("📭 Universe 시트의 Ticker_Arin이 비어 있어요.")
        return

    eps_panel = _aligned_panel("BEST_EPS")
    sales_panel = _aligned_panel("BEST_SALES")

    in_panel = [t for t in universe if t in eps_panel.columns and t in sales_panel.columns]
    missing = [t for t in universe if t not in in_panel]
    if missing:
        st.caption(f"ℹ️ 데이터 없음 (BEST_EPS / BEST_SALES 미수록): {', '.join(missing)}")
    if not in_panel:
        st.warning("Universe 종목 중 BEST_EPS / BEST_SALES에 매칭되는 티커가 없어요.")
        return

    default = in_panel[: min(3, len(in_panel))]
    selected = st.multiselect(
        "분석할 종목 선택",
        options=in_panel, default=default,
        help="Ticker_Arin 중 Bloomberg 컨센서스(BEST_EPS / BEST_SALES)가 있는 종목만 표시.",
    )
    if not selected:
        st.info("종목을 1개 이상 선택해 주세요.")
        return

    horizon_tabs = st.tabs(["📅 3개월 모멘텀", "📅 12개월 모멘텀"])
    with horizon_tabs[0]:
        _render_horizon_section("3M", LOOKBACK_3M, eps_panel, sales_panel, selected)
    with horizon_tabs[1]:
        _render_horizon_section("12M", LOOKBACK_12M, eps_panel, sales_panel, selected)
