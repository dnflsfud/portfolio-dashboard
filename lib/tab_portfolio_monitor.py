"""Portfolio monitoring tab for 아린이's holdings (Self_Port.xlsx Sheet2).

Each row in Sheet2 is treated as a *transaction*:
  - ``Number > 0`` → buy  (positive shares acquired at ``Entry_Price``)
  - ``Number < 0`` → sell (negative shares released at ``Entry_Price``)

Aggregation per ticker:
  net_shares       = Σ Number_i
  total_buys_$     = Σ (Number_i × Entry_Price_i)  for buys
  total_sells_$    = Σ (-Number_i × Entry_Price_i)  for sells (cash returned)
  avg_buy_cost     = total_buys_$ / total_shares_bought
  market_value(t)  = net_shares × price(t)
  cum_return(t)    = (market_value(t) + total_sells_$ — that point in time) / total_buys_$ — 1

This gives a single cumulative-return number that correctly accounts for
follow-on buys and partial sells (cash returned from sells re-enters the
numerator alongside remaining market value, so the chart line is continuous).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .data_loader import load_self_port_holdings, load_px_last
from .calendar_utils import get_business_calendar
from .live_price import fetch_yahoo_latest, yfinance_available


UP_THRESHOLD = 0.1   # >= +0.1%  -> 📈
DOWN_THRESHOLD = -0.1  # <= -0.1%  -> 📉


def _emoji(daily_return_pct: float) -> str:
    """Compact 1-emoji indicator for cards/charts (line-height friendly)."""
    if pd.isna(daily_return_pct):
        return "❓"
    if daily_return_pct >= UP_THRESHOLD:
        return "📈"
    if daily_return_pct <= DOWN_THRESHOLD:
        return "📉"
    return "➡️"


# Tiered "kid-friendly" emoji used in the monthly daily-return view.
# More tiers + cuter pictograms so a 6-year-old can grok at-a-glance.
def _cute_emoji(pct: float) -> str:
    if pd.isna(pct):
        return "🤔"
    if pct >= 3.0:
        return "🚀"
    if pct >= 1.0:
        return "🥳"
    if pct >= 0.3:
        return "🌈"
    if pct >= UP_THRESHOLD:
        return "🌟"
    if pct <= -3.0:
        return "😭"
    if pct <= -1.0:
        return "😢"
    if pct <= -0.3:
        return "🥲"
    if pct <= DOWN_THRESHOLD:
        return "🌧️"
    return "😴"


_CUTE_LEGEND = [
    ("🚀", "+3.0% 이상"),
    ("🥳", "+1.0% ~ +3.0%"),
    ("🌈", "+0.3% ~ +1.0%"),
    ("🌟", "+0.1% ~ +0.3%"),
    ("😴", "−0.1% ~ +0.1% (보합)"),
    ("🌧️", "−0.3% ~ −0.1%"),
    ("🥲", "−1.0% ~ −0.3%"),
    ("😢", "−3.0% ~ −1.0%"),
    ("😭", "−3.0% 이하"),
    ("🤔", "데이터 없음"),
]


# --------------------------------------------------------------------------- #
# Transactions → per-ticker positions                                         #
# --------------------------------------------------------------------------- #
def _normalize_transactions(holdings: pd.DataFrame) -> pd.DataFrame:
    """Coerce types and sort by Date.  Each row is one transaction."""
    if holdings.empty:
        return holdings
    h = holdings.copy()
    h["Date"] = pd.to_datetime(h["Date"])
    h["Ticker"] = h["Ticker"].astype(str).str.strip()
    h["Number"] = pd.to_numeric(h["Number"], errors="coerce").fillna(0).astype(float)
    h["Entry_Price"] = pd.to_numeric(h["Entry_Price"], errors="coerce")
    return h.sort_values(["Ticker", "Date"]).reset_index(drop=True)


def _aggregate_by_ticker(holdings: pd.DataFrame) -> pd.DataFrame:
    """Collapse transactions to one row per ticker.

    Columns: first_date, last_date, n_txns, n_buys, n_sells,
             total_shares_bought, total_shares_sold, net_shares,
             total_buys_$, total_sells_$, avg_buy_cost.
    """
    if holdings.empty:
        return pd.DataFrame()

    txns = _normalize_transactions(holdings)
    rows = []
    for ticker, grp in txns.groupby("Ticker", sort=False):
        buys = grp[grp["Number"] > 0]
        sells = grp[grp["Number"] < 0]
        total_shares_bought = float(buys["Number"].sum())
        total_shares_sold = float(-sells["Number"].sum())
        total_buys_dollars = float((buys["Number"] * buys["Entry_Price"]).sum())
        total_sells_dollars = float((-sells["Number"] * sells["Entry_Price"]).sum())
        avg_buy_cost = (
            total_buys_dollars / total_shares_bought
            if total_shares_bought > 0
            else np.nan
        )
        rows.append({
            "ticker": ticker,
            "first_date": grp["Date"].min(),
            "last_date": grp["Date"].max(),
            "n_txns": int(len(grp)),
            "n_buys": int(len(buys)),
            "n_sells": int(len(sells)),
            "total_shares_bought": total_shares_bought,
            "total_shares_sold": total_shares_sold,
            "net_shares": float(grp["Number"].sum()),
            "total_buys_$": total_buys_dollars,
            "total_sells_$": total_sells_dollars,
            "avg_buy_cost": avg_buy_cost,
        })
    return pd.DataFrame(rows).set_index("ticker")


# --------------------------------------------------------------------------- #
# Live current price (PX_LAST or yfinance fallback)                           #
# --------------------------------------------------------------------------- #
def _current_price(
    ticker: str,
    entry_dates: pd.Series,
    px_panel: pd.DataFrame,
    *,
    use_yahoo_fallback: bool,
    business_calendar: pd.DatetimeIndex | None,
) -> Tuple[float | None, pd.Timestamp | None, str]:
    """Return (price, asof_date, source) for the LATEST quote on a ticker.

    Source priority:
      1. PX_LAST on/after the LATEST transaction date (covers all transactions).
      2. yfinance latest, if PX_LAST is older than (a) latest transaction or
         (b) the master business-day calendar's last day.
      3. Last available PX_LAST (informational only) → marked stale.
    """
    last_biz = business_calendar.max() if business_calendar is not None and len(business_calendar) else None
    series = px_panel[ticker].dropna() if ticker in px_panel.columns else pd.Series(dtype=float)
    px_last_max = series.index.max() if not series.empty else pd.NaT
    latest_txn = pd.Timestamp(entry_dates.max()) if len(entry_dates) else pd.NaT

    px_covers_txns = (
        not series.empty
        and (pd.isna(latest_txn) or px_last_max >= latest_txn)
    )
    px_at_latest_biz = (
        last_biz is None
        or pd.isna(px_last_max)
        or pd.Timestamp(px_last_max).normalize() >= pd.Timestamp(last_biz).normalize()
    )

    if px_covers_txns and px_at_latest_biz:
        return float(series.iloc[-1]), series.index[-1], "PX_LAST"

    if use_yahoo_fallback and yfinance_available():
        yp, yd = fetch_yahoo_latest(ticker)
        if yp is not None:
            return float(yp), (yd if yd is not None else pd.Timestamp.utcnow().normalize()), "yahoo"

    if not series.empty:
        return float(series.iloc[-1]), series.index[-1], "PX_LAST(stale)"

    return None, None, "none"


def _compute_returns(
    holdings: pd.DataFrame,
    px_panel: pd.DataFrame,
    *,
    use_yahoo_fallback: bool = True,
    business_calendar: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Aggregate per-ticker summary used by the holding cards.

    Columns: first_date, last_date, n_txns, n_buys, n_sells, net_shares,
    total_shares_bought, total_shares_sold, total_buys_$, total_sells_$,
    avg_buy_cost, current_price, current_date, market_value, realized_pnl_$,
    unrealized_pnl_$, total_pnl_$, cum_return_pct, status_emoji, source, stale.
    """
    agg = _aggregate_by_ticker(holdings)
    if agg.empty:
        return agg

    rows = []
    for ticker, r in agg.iterrows():
        ent_dates = holdings.loc[holdings["Ticker"] == ticker, "Date"]
        cur_price, cur_date, source = _current_price(
            ticker, ent_dates, px_panel,
            use_yahoo_fallback=use_yahoo_fallback,
            business_calendar=business_calendar,
        )
        market_value = (r["net_shares"] * cur_price) if cur_price is not None else np.nan
        realized = float(r["total_sells_$"]) - float(r["total_shares_sold"]) * float(r["avg_buy_cost"]) \
            if r["total_shares_sold"] > 0 and pd.notna(r["avg_buy_cost"]) else 0.0
        unrealized = (market_value - r["net_shares"] * r["avg_buy_cost"]) \
            if (cur_price is not None and pd.notna(r["avg_buy_cost"])) else np.nan
        total_pnl = (
            (market_value + r["total_sells_$"]) - r["total_buys_$"]
            if cur_price is not None else np.nan
        )
        cum_pct = (total_pnl / r["total_buys_$"] * 100) \
            if (cur_price is not None and r["total_buys_$"] > 0) else np.nan
        stale = source == "PX_LAST(stale)"
        if stale:
            emo = "⏳"
        elif source == "none" or pd.isna(cum_pct):
            emo = "❓"
        else:
            emo = _emoji(cum_pct)
        rows.append({
            **r.to_dict(),
            "ticker": ticker,
            "current_price": cur_price if cur_price is not None else np.nan,
            "current_date": cur_date if cur_date is not None else pd.NaT,
            "market_value": market_value,
            "realized_pnl_$": realized,
            "unrealized_pnl_$": unrealized,
            "total_pnl_$": total_pnl,
            "cum_return_pct": cum_pct,
            "status_emoji": emo,
            "source": source,
            "stale": stale,
        })
    return pd.DataFrame(rows).set_index("ticker")


# --------------------------------------------------------------------------- #
# Time-series helpers (transaction-aware)                                     #
# --------------------------------------------------------------------------- #
def _per_ticker_cum_series(
    txns_for_ticker: pd.DataFrame,
    px_panel: pd.DataFrame,
    ticker: str,
) -> pd.Series:
    """Cumulative return % over time for ONE ticker, transaction-aware.

    On every business day t with PX_LAST data:
      net_shares(t)    = Σ Number for txns with date ≤ t
      total_buys$(t)   = Σ (Number×Price) for buys with date ≤ t
      total_sells$(t)  = Σ (-Number×Price) for sells with date ≤ t
      market_value(t)  = net_shares(t) × price(t)
      cum_return(t)    = (market_value(t) + total_sells$(t)) / total_buys$(t) − 1
    """
    if ticker not in px_panel.columns or txns_for_ticker.empty:
        return pd.Series(dtype=float)

    earliest = pd.Timestamp(txns_for_ticker["Date"].min())
    prices = px_panel[ticker].dropna()
    prices = prices[prices.index >= earliest]
    if prices.empty:
        return pd.Series(dtype=float)

    txns = txns_for_ticker.copy()
    txns["Date"] = pd.to_datetime(txns["Date"])

    out_idx, out_val = [], []
    for d in prices.index:
        active = txns[txns["Date"] <= d]
        if active.empty:
            continue
        buys = active[active["Number"] > 0]
        sells = active[active["Number"] < 0]
        total_buys = float((buys["Number"] * buys["Entry_Price"]).sum())
        total_sells = float((-sells["Number"] * sells["Entry_Price"]).sum())
        net_shares = float(active["Number"].sum())
        if total_buys <= 0:
            continue
        market_value = net_shares * float(prices.loc[d])
        cum_pct = ((market_value + total_sells) / total_buys - 1.0) * 100
        out_idx.append(d)
        out_val.append(cum_pct)

    return pd.Series(out_val, index=pd.DatetimeIndex(out_idx), name=ticker)


def _total_cumulative_series(
    holdings: pd.DataFrame,
    px_panel: pd.DataFrame,
) -> pd.Series:
    """Aggregate transaction-aware cumulative return across all tickers.

    For each business day t (union of trading days for every ticker held):
      total_buys$(t)    = Σ_i (buy txns for ticker i with date ≤ t).$ amount
      total_sells$(t)   = Σ_i (sell txns for ticker i with date ≤ t).$ amount
      market_value(t)   = Σ_i net_shares_i(t) × price_i(t)
      cum_return(t)     = (market_value(t) + total_sells$(t)) / total_buys$(t) − 1
    """
    if holdings.empty:
        return pd.Series(dtype=float)
    txns = _normalize_transactions(holdings)
    earliest = pd.Timestamp(txns["Date"].min())

    ticker_prices: Dict[str, pd.Series] = {}
    union_dates: set = set()
    for ticker in txns["Ticker"].unique():
        if ticker not in px_panel.columns:
            continue
        s = px_panel[ticker].dropna()
        s = s[s.index >= earliest]
        if not s.empty:
            ticker_prices[ticker] = s
            union_dates.update(s.index)
    if not ticker_prices:
        return pd.Series(dtype=float)

    all_dates = sorted(union_dates)
    out_idx, out_val = [], []
    for d in all_dates:
        active = txns[txns["Date"] <= d]
        if active.empty:
            continue
        buys = active[active["Number"] > 0]
        sells = active[active["Number"] < 0]
        total_buys = float((buys["Number"] * buys["Entry_Price"]).sum())
        total_sells = float((-sells["Number"] * sells["Entry_Price"]).sum())
        if total_buys <= 0:
            continue
        market_value = 0.0
        for ticker, grp in active.groupby("Ticker"):
            net_shares = float(grp["Number"].sum())
            if net_shares == 0 or ticker not in ticker_prices:
                continue
            prices = ticker_prices[ticker]
            if d in prices.index:
                p = float(prices.loc[d])
            else:
                avail = prices[prices.index <= d]
                if avail.empty:
                    continue
                p = float(avail.iloc[-1])
            market_value += net_shares * p
        cum_pct = ((market_value + total_sells) / total_buys - 1.0) * 100
        out_idx.append(d)
        out_val.append(cum_pct)
    return pd.Series(out_val, index=pd.DatetimeIndex(out_idx), name="총합")


def _daily_returns_panel(holdings: pd.DataFrame, px_panel: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker daily % change (close-to-close) since first transaction date.

    Aggregates by ticker first, then takes pct_change of PX_LAST from the
    ticker's first transaction onward.
    """
    if holdings.empty:
        return pd.DataFrame()
    txns = _normalize_transactions(holdings)
    parts: Dict[str, pd.Series] = {}
    for ticker, grp in txns.groupby("Ticker", sort=False):
        if ticker not in px_panel.columns:
            continue
        first = pd.Timestamp(grp["Date"].min())
        s = px_panel[ticker].dropna()
        s = s[s.index >= first]
        if len(s) < 2:
            continue
        parts[ticker] = s.pct_change().dropna() * 100
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, axis=1)


# --------------------------------------------------------------------------- #
# Renderers                                                                   #
# --------------------------------------------------------------------------- #
_SOURCE_BADGE = {
    "PX_LAST": "📅 PX_LAST",
    "yahoo": "🌐 Yahoo Finance",
    "PX_LAST(stale)": "⏳ PX_LAST (오래됨)",
    "none": "❓ 데이터 없음",
}


def _render_holding_cards(returns_df: pd.DataFrame) -> None:
    if returns_df.empty:
        return
    cols = st.columns(min(len(returns_df), 4))
    for i, (ticker, row) in enumerate(returns_df.iterrows()):
        with cols[i % len(cols)]:
            avg_cost = row["avg_buy_cost"]
            cur = row["current_price"]
            cum = row["cum_return_pct"]
            emo = row["status_emoji"]
            net = row["net_shares"]
            n_buys = int(row["n_buys"])
            n_sells = int(row["n_sells"])
            cur_date = row["current_date"]
            source = row["source"]
            badge = _SOURCE_BADGE.get(source, "")

            buy_label = f"평단가 ${avg_cost:,.2f}" if n_buys > 1 else f"진입가 ${avg_cost:,.2f}"

            if pd.isna(cur):
                st.metric(
                    label=f"{emo}  {ticker}",
                    value="데이터 없음",
                    delta=buy_label,
                )
                st.caption(badge)
            elif row["stale"]:
                st.metric(
                    label=f"{emo}  {ticker}",
                    value=buy_label.replace("평단가 ", "").replace("진입가 ", ""),
                    delta="가격 갱신 대기",
                )
                if pd.notna(cur_date):
                    st.caption(f"{badge}  최근값 {pd.Timestamp(cur_date).date()} ${cur:,.2f}")
                else:
                    st.caption(badge)
            else:
                st.metric(
                    label=f"{emo}  {ticker}",
                    value=f"${cur:,.2f}",
                    delta=f"{cum:+.2f}%  ({buy_label})",
                )
                lines = []
                if pd.notna(cur_date):
                    lines.append(f"{badge}  {pd.Timestamp(cur_date).date()} 기준")
                else:
                    lines.append(badge)
                lines.append(
                    f"📦 보유 {net:g}주 · 매수 {n_buys}회"
                    + (f" · 매도 {n_sells}회" if n_sells else "")
                )
                st.caption("  ·  ".join(lines))


def _render_cumulative_chart(
    holdings: pd.DataFrame,
    px_panel: pd.DataFrame,
    *,
    mode: str = "종목별 + 총합",
) -> None:
    fig = go.Figure()
    plotted = 0
    txns = _normalize_transactions(holdings)

    if mode in ("종목별", "종목별 + 총합"):
        for ticker, grp in txns.groupby("Ticker", sort=False):
            cum = _per_ticker_cum_series(grp, px_panel, ticker)
            if cum.empty:
                continue
            fig.add_trace(go.Scatter(
                x=cum.index, y=cum.values, mode="lines+markers", name=ticker,
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}%<extra>" + ticker + "</extra>",
            ))
            plotted += 1

    if mode in ("총합", "종목별 + 총합"):
        total = _total_cumulative_series(holdings, px_panel)
        if not total.empty:
            fig.add_trace(go.Scatter(
                x=total.index, y=total.values, mode="lines+markers",
                name="🎯 총합 (가중)",
                line=dict(color="#111111", width=4, dash="solid"),
                hovertemplate="%{x|%Y-%m-%d}<br><b>총합 %{y:+.2f}%</b><extra></extra>",
            ))
            plotted += 1

    if plotted == 0:
        st.info("📭 그래프를 그릴 가격 데이터가 아직 없어요.")
        return

    # Mark each transaction as a vertical guide on the chart.
    # Use add_shape + add_annotation (separate calls) — plotly's add_vline with
    # annotation_text fails on Timestamps in pandas 3.0 (sum of Timestamps).
    for _, t in txns.iterrows():
        if pd.isna(t["Date"]):
            continue
        is_buy = t["Number"] > 0
        color = "#16a34a" if is_buy else "#dc2626"
        symbol = "🟢" if is_buy else "🔴"
        x_str = pd.Timestamp(t["Date"]).strftime("%Y-%m-%d")
        fig.add_shape(
            type="line", xref="x", yref="paper",
            x0=x_str, x1=x_str, y0=0, y1=1,
            line=dict(color=color, width=1, dash="dot"), opacity=0.35,
        )
        fig.add_annotation(
            x=x_str, y=1.02, xref="x", yref="paper",
            text=f"{symbol} {t['Ticker'].split()[0]} {t['Number']:+g}@${t['Entry_Price']:.0f}",
            showarrow=False, font=dict(size=9, color=color),
            xanchor="left",
        )

    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title=f"🎀 누적 수익률 (%)  — 진입가 기준   |   보기: {mode}",
        yaxis_title="수익률 (%)",
        xaxis_title="날짜",
        height=460,
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.2),
    )
    st.plotly_chart(fig, width="stretch")


def _months_between(start: pd.Timestamp, end: pd.Timestamp) -> List[str]:
    months = pd.date_range(start.to_period("M").to_timestamp(),
                           end.to_period("M").to_timestamp(),
                           freq="MS")
    return [m.strftime("%Y-%m") for m in months]


def _daily_html_table(sub: pd.DataFrame) -> str:
    """Render a month's daily returns as a chunky, kid-friendly HTML table.

    Big emoji (≈2.6em) on top of each cell; signed percent below in green/red.
    """
    headers = "".join(
        f"<th style='padding:10px 14px; text-align:center; "
        f"background:#f3f4f6; border-bottom:2px solid #d1d5db; "
        f"font-weight:700; color:#111;'>{t.split()[0]}</th>"
        for t in sub.columns
    )
    rows_html = []
    for d, row in sub.iterrows():
        cells = []
        for ticker in sub.columns:
            v = row[ticker]
            emo = _cute_emoji(v)
            if pd.isna(v):
                cell = (
                    "<div style='font-size:2.6em; line-height:1;'>🤔</div>"
                    "<div style='color:#9ca3af; font-size:0.95em; margin-top:4px;'>—</div>"
                )
            else:
                color = "#16a34a" if v >= UP_THRESHOLD else (
                    "#dc2626" if v <= DOWN_THRESHOLD else "#6b7280"
                )
                cell = (
                    f"<div style='font-size:2.6em; line-height:1;'>{emo}</div>"
                    f"<div style='color:{color}; font-weight:700; "
                    f"font-size:1.05em; margin-top:4px;'>{v:+.2f}%</div>"
                )
            cells.append(
                f"<td style='padding:10px 14px; text-align:center; "
                f"border-bottom:1px solid #e5e7eb;'>{cell}</td>"
            )
        rows_html.append(
            f"<tr><td style='padding:10px 14px; font-weight:700; color:#374151; "
            f"white-space:nowrap; border-bottom:1px solid #e5e7eb;'>📅 "
            f"{d.strftime('%m월 %d일')}</td>"
            f"{''.join(cells)}</tr>"
        )
    return (
        "<div style='overflow-x:auto;'>"
        "<table style='border-collapse:collapse; width:100%; "
        "font-family: -apple-system, BlinkMacSystemFont, sans-serif;'>"
        "<thead><tr>"
        "<th style='padding:10px 14px; text-align:left; background:#f3f4f6; "
        "border-bottom:2px solid #d1d5db;'>날짜</th>"
        f"{headers}"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table></div>"
    )


def _render_monthly_tabs(holdings: pd.DataFrame, daily_returns: pd.DataFrame) -> None:
    if daily_returns.empty:
        st.info("📭 일별 수익률을 계산할 데이터가 아직 없어요.")
        return
    earliest_entry = pd.to_datetime(holdings["Date"]).min()
    latest = daily_returns.index.max()
    months = _months_between(earliest_entry, latest)
    if not months:
        st.info("📅 표시할 월이 없어요.")
        return

    tabs = st.tabs([f"📅 {m}" for m in months])
    for tab, ym in zip(tabs, months):
        with tab:
            sub = daily_returns.loc[daily_returns.index.strftime("%Y-%m") == ym]
            if sub.empty:
                st.write("이 달에는 거래일이 없거나 보유 시작 전이에요.")
                continue
            sub = sub.round(2).sort_index()
            st.markdown(_daily_html_table(sub), unsafe_allow_html=True)


def _render_transaction_log(holdings: pd.DataFrame) -> None:
    """A flat transaction log so the user can sanity-check what's loaded."""
    if holdings.empty:
        return
    txns = _normalize_transactions(holdings).copy()
    txns["거래"] = txns["Number"].apply(lambda x: "🟢 매수" if x > 0 else ("🔴 매도" if x < 0 else "—"))
    txns["수량"] = txns["Number"].abs()
    txns["가격"] = txns["Entry_Price"].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "—")
    txns["체결금액"] = (txns["Number"].abs() * txns["Entry_Price"]).apply(
        lambda x: f"${x:,.2f}" if pd.notna(x) else "—"
    )
    txns["날짜"] = pd.to_datetime(txns["Date"]).dt.date
    cols = ["날짜", "Ticker", "거래", "수량", "가격", "체결금액"]
    st.dataframe(txns[cols], width="stretch", hide_index=True)


def render_portfolio_monitor_tab() -> None:
    """Public entry point — render 아린이's portfolio monitor."""
    st.header("🎀 아린이의 포트폴리오 모니터")

    holdings = load_self_port_holdings()
    if holdings.empty:
        st.info("📭 아직 보유한 종목이 없어요!  Self_Port.xlsx의 Sheet2에 데이터를 추가해 주세요.")
        return

    px_panel = load_px_last()
    cal = get_business_calendar()
    use_yahoo = st.sidebar.toggle(
        "🌐 Yahoo Finance 라이브 가격 사용",
        value=True,
        help="PX_LAST가 진입일보다 오래되었거나 최신 영업일이 아니면 Yahoo Finance에서 최신가를 가져옵니다.",
    )
    returns_df = _compute_returns(
        holdings, px_panel,
        use_yahoo_fallback=use_yahoo,
        business_calendar=cal,
    )

    sources = set(returns_df["source"].unique())
    if "yahoo" in sources:
        st.success("🌐 PX_LAST가 오래되어 일부/전체 가격을 Yahoo Finance에서 가져왔어요.")
    if returns_df["stale"].any():
        st.warning(
            "⏳ 일부 종목은 어떤 소스에서도 최신가를 찾지 못했어요. "
            "S&P500_filtered.xlsx 갱신 또는 사이드바의 Yahoo 토글을 확인해 주세요."
        )

    st.subheader("📊 보유 종목 현황 (티커별 합산)")
    _render_holding_cards(returns_df)

    # Portfolio-level summary
    total_buys = float(returns_df["total_buys_$"].sum())
    total_sells = float(returns_df["total_sells_$"].sum())
    total_mv = float(returns_df["market_value"].sum(skipna=True))
    if total_buys > 0:
        port_cum = ((total_mv + total_sells) / total_buys - 1.0) * 100
        port_pnl = (total_mv + total_sells) - total_buys
        c1, c2, c3 = st.columns(3)
        c1.metric("💼 총 매수금액", f"${total_buys:,.2f}")
        c2.metric("💰 현재 평가 + 매도수령", f"${total_mv + total_sells:,.2f}",
                  delta=f"{port_cum:+.2f}%")
        c3.metric("📊 손익", f"${port_pnl:+,.2f}")

    st.divider()
    st.subheader("📈 누적 수익률 그래프")
    chart_mode = st.radio(
        "보기 방식",
        options=["종목별 + 총합", "종목별", "총합"],
        index=0, horizontal=True,
        help=(
            "각 시점의 누적 수익률 = (현재 시장가치 + 매도 수령액) ÷ 누적 매수금액 − 1.\n"
            "추가 매수 / 부분 매도가 모두 반영됩니다.\n"
            "그래프 위 점선은 거래 이벤트(🟢 매수 / 🔴 매도)예요."
        ),
    )
    _render_cumulative_chart(holdings, px_panel, mode=chart_mode)

    st.divider()
    st.subheader("📅 월별 일일 수익률")
    daily = _daily_returns_panel(holdings, px_panel)
    _render_monthly_tabs(holdings, daily)

    st.divider()
    with st.expander("📋 거래 내역 보기", expanded=False):
        _render_transaction_log(holdings)

    with st.expander("ℹ️ 이모지 안내"):
        legend_html = (
            "<div style='display:grid; grid-template-columns:repeat(2, minmax(160px,1fr)); "
            "gap:8px 16px; padding:6px 4px;'>"
            + "".join(
                f"<div style='display:flex; align-items:center; gap:10px;'>"
                f"<span style='font-size:1.9em;'>{emo}</span>"
                f"<span style='font-size:0.95em; color:#374151;'>{label}</span>"
                f"</div>"
                for emo, label in _CUTE_LEGEND
            )
            + "</div>"
            "<div style='margin-top:10px; color:#6b7280; font-size:0.9em;'>"
            "보유 종목 카드의 신호(📈 / ➡️ / 📉 / ⏳ / ❓)는 누적 수익률 기준이에요."
            "</div>"
        )
        st.markdown(legend_html, unsafe_allow_html=True)
