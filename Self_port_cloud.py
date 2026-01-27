# -*- coding: utf-8 -*-
"""
Self_Port.py - Personal Portfolio Dashboard (Streamlit Cloud Version)
----------------------------------------------------------------------
개인 포트폴리오 분석 대시보드 - Streamlit Cloud 배포용

실행:
  streamlit run Self_port_cloud.py
"""

import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime
import itertools

st.set_page_config(page_title="Personal Portfolio Dashboard", layout="wide")

# ------------------------------------------------------------------------------------
# Configuration - Streamlit Cloud용 상대 경로
# ------------------------------------------------------------------------------------
# 현재 파일 기준 상대 경로 사용
BASE_DIR = Path(__file__).parent

PORT_FILE = BASE_DIR / "data" / "Self_Port.xlsx"
SP500_FILE = BASE_DIR / "data" / "S&P500.xlsx"
FACTSET_FILE = BASE_DIR / "data" / "D_Factset_Tech.xlsx"

# RL Portfolio Result Files
RL_RESULT_DIR = BASE_DIR / "result"
RL_DAILY_PERF_FILE = RL_RESULT_DIR / "daily_performance.csv"
RL_MONTHLY_WEIGHTS_FILE = RL_RESULT_DIR / "monthly_weights.csv"
RL_FEATURES_DIR = RL_RESULT_DIR / "features"

COLOR_POSITIVE = "#2ca02c"
COLOR_NEGATIVE = "#d62728"
COLOR_BLUE = "#1f77b4"
COLOR_ORANGE = "#ff7f0e"

TRADING_DAYS = 252

# Transaction cost (based on NVIDIA example: 0.5% when entry price = current price)
TRANSACTION_COST_RATE = 0.005  # 0.5%

# Period colors for time progression arrows
PERIOD_COLORS = {
    'Now': '#1f77b4',      # Blue
    '2W ago': '#9467bd',   # Purple
    '1M ago': '#ff7f0e',   # Orange
    '3M ago': '#d62728'    # Red
}

PERIODS = {"Now": 0, "2W ago": 10, "1M ago": 21, "3M ago": 63}

METRIC_LABELS = {
    "BEST_EPS": "Forward EPS",
    "BEST_SALES": "Forward Sales",
    "BEST_CALCULATED_FCF": "Forward FCF",
    "BEST_PE_RATIO": "Forward P/E",
    "BEST_GROSS_MARGIN": "Gross Margin",
    "BEST_ROE": "Forward ROE",
    "OPER_MARGIN": "Operating Margin",
    "BEST_PEG_RATIO": "PEG Ratio",
    "CUR_MKT_CAP": "Market Cap",
    "BEST_EV_TO_BEST_EBITDA": "EV/EBITDA",
}


# ------------------------------------------------------------------------------------
# Utility Functions
# ------------------------------------------------------------------------------------
def format_percentage(v, decimals=2):
    if pd.isna(v):
        return "-"
    return f"{float(v) * 100:.{decimals}f}%"


def _short_ticker(ticker: str) -> str:
    """GOOGL US Equity -> GOOGL"""
    return str(ticker).split()[0] if ticker else ticker


def _normalize_ticker(ticker: str) -> str:
    """Normalize ticker format"""
    return str(ticker).strip()


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _calc_cagr(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return float("nan")
    nav = (1.0 + r).cumprod()
    years = len(r) / float(TRADING_DAYS)
    if years <= 0:
        return float("nan")
    return float(nav.iloc[-1] ** (1.0 / years) - 1.0)


def _calc_sharpe(returns: pd.Series, rf: float = 0.02) -> float:
    r = returns.dropna()
    if r.empty:
        return float("nan")
    vol = float(r.std(ddof=1) * np.sqrt(float(TRADING_DAYS)))
    if vol == 0 or np.isnan(vol):
        return float("nan")
    ann_ret = float(r.mean() * float(TRADING_DAYS))
    return float((ann_ret - rf) / vol)


def _calc_maxdd(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return float("nan")
    nav = (1.0 + r).cumprod()
    peak = nav.cummax()
    dd = nav.div(peak).sub(1.0)
    return float(dd.min())


# ------------------------------------------------------------------------------------
# Data Loading
# ------------------------------------------------------------------------------------
@st.cache_data(show_spinner=True)
def load_portfolio() -> pd.DataFrame:
    """Load portfolio from Self_Port.xlsx"""
    if not PORT_FILE.exists():
        st.error(f"Portfolio file not found: {PORT_FILE}")
        return pd.DataFrame()

    df = pd.read_excel(PORT_FILE, sheet_name="Sheet1", engine="openpyxl")
    df['Date'] = pd.to_datetime(df['Date'])
    df['Ticker'] = df['Ticker'].astype(str).str.strip()
    return df


@st.cache_data(show_spinner=True)
def load_sp500_data() -> Dict[str, pd.DataFrame]:
    """Load all sheets from S&P500.xlsx"""
    if not SP500_FILE.exists():
        st.error(f"S&P500 file not found: {SP500_FILE}")
        return {}

    data = {}
    xl = pd.ExcelFile(SP500_FILE, engine="openpyxl")

    for sheet in xl.sheet_names:
        df = pd.read_excel(xl, sheet_name=sheet)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
        data[sheet] = df

    return data


@st.cache_data(show_spinner=True)
def load_factset_revision() -> Dict[str, pd.DataFrame]:
    """Load Factset revision data from D_Factset_Tech.xlsx"""
    if not FACTSET_FILE.exists():
        st.warning(f"Factset file not found: {FACTSET_FILE}")
        return {}

    data = {}
    xl = pd.ExcelFile(FACTSET_FILE, engine="openpyxl")

    # Load EPS and Sales revision sheets
    revision_sheets = ['Fwd SP50 Revision Rate', 'Sales_Revision']

    for sheet in revision_sheets:
        if sheet in xl.sheet_names:
            df = pd.read_excel(xl, sheet_name=sheet)

            # First row contains ticker codes, first column is date
            if len(df) > 1:
                # Get tickers from first row (row 0)
                tickers = df.iloc[0, 1:].values

                # Get data from row 1 onwards
                df_data = df.iloc[1:].copy()
                df_data.columns = ['date'] + list(tickers)

                # Parse dates
                df_data['date'] = pd.to_datetime(df_data['date'], errors='coerce')
                df_data = df_data.dropna(subset=['date'])
                df_data = df_data.set_index('date').sort_index()

                # Convert to numeric
                df_data = _coerce_numeric(df_data)

                data[sheet] = df_data

    return data


# ------------------------------------------------------------------------------------
# RL Portfolio Data Loading
# ------------------------------------------------------------------------------------
@st.cache_data(show_spinner=True)
def load_rl_daily_performance() -> pd.DataFrame:
    """Load RL portfolio daily performance"""
    if not RL_DAILY_PERF_FILE.exists():
        return pd.DataFrame()

    df = pd.read_csv(RL_DAILY_PERF_FILE, parse_dates=['date'])
    df = df.set_index('date').sort_index()
    return df


@st.cache_data(show_spinner=True)
def load_rl_monthly_weights() -> pd.DataFrame:
    """Load RL portfolio monthly weights"""
    if not RL_MONTHLY_WEIGHTS_FILE.exists():
        return pd.DataFrame()

    df = pd.read_csv(RL_MONTHLY_WEIGHTS_FILE, parse_dates=['date'])
    df = df.set_index('date').sort_index()
    return df


@st.cache_data(show_spinner=True)
def load_rl_features() -> Dict[str, pd.DataFrame]:
    """Load all feature CSVs from RL result directory"""
    features = {}
    if not RL_FEATURES_DIR.exists():
        return features

    for csv_file in RL_FEATURES_DIR.glob("*.csv"):
        feature_name = csv_file.stem.replace("feature_", "").upper()
        df = pd.read_csv(csv_file, parse_dates=['date'])
        df = df.set_index('date').sort_index()
        features[feature_name] = df

    return features


def calc_rl_period_returns(daily_perf: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Calculate period returns for RL portfolio (1M, 3M, 6M, 12M)"""
    if daily_perf.empty:
        return {}

    latest_date = daily_perf.index.max()
    periods = {
        '1M': 21,
        '3M': 63,
        '6M': 126,
        '12M': 252
    }

    results = {'portfolio': {}, 'benchmark': {}, 'excess': {}}

    for period_name, days in periods.items():
        if len(daily_perf) >= days:
            start_idx = max(0, len(daily_perf) - days)
            period_data = daily_perf.iloc[start_idx:]

            # Calculate cumulative return for the period
            port_cum = (1 + period_data['portfolio_return']).prod() - 1
            bm_cum = (1 + period_data['benchmark_return']).prod() - 1
            excess = port_cum - bm_cum

            results['portfolio'][period_name] = port_cum
            results['benchmark'][period_name] = bm_cum
            results['excess'][period_name] = excess
        else:
            results['portfolio'][period_name] = np.nan
            results['benchmark'][period_name] = np.nan
            results['excess'][period_name] = np.nan

    return results


def get_latest_business_date(sp500_data: Dict[str, pd.DataFrame]) -> pd.Timestamp:
    """Get latest business date from SPX Index sheet"""
    if 'SPX Index' not in sp500_data:
        return pd.Timestamp.now()

    spx = sp500_data['SPX Index']
    if spx.empty:
        return pd.Timestamp.now()

    # SPX Index has date as index
    return spx.index.max()


def get_portfolio_with_prices(portfolio: pd.DataFrame, sp500_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Merge portfolio with latest prices from S&P500.xlsx"""
    if 'PX_LAST' not in sp500_data:
        return portfolio

    prices = sp500_data['PX_LAST']
    latest_date = get_latest_business_date(sp500_data)

    # Get latest available prices
    latest_prices = prices.loc[prices.index <= latest_date].iloc[-1] if len(prices) > 0 else pd.Series()

    portfolio = portfolio.copy()
    portfolio['Current_Price'] = portfolio['Ticker'].map(lambda t: latest_prices.get(t, np.nan))
    portfolio['Entry_Value'] = portfolio['Number'] * portfolio['Entry_Price']
    portfolio['Current_Value'] = portfolio['Number'] * portfolio['Current_Price']
    portfolio['PnL'] = portfolio['Current_Value'] - portfolio['Entry_Value']
    portfolio['Return'] = portfolio['PnL'] / portfolio['Entry_Value']

    return portfolio


# ------------------------------------------------------------------------------------
# Charting Functions
# ------------------------------------------------------------------------------------
def plot_valuation_bands(data: pd.DataFrame, tickers: List[str], title: str = "Valuation Range") -> go.Figure:
    """Plot valuation bands with quantiles, 1-month ago, and latest values"""

    # Filter for available tickers
    available = [t for t in tickers if t in data.columns]
    if not available:
        return go.Figure()

    data_subset = data[available].dropna(how='all')
    if data_subset.empty or len(data_subset) < 22:
        return go.Figure()

    quantiles = data_subset.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    recent_val = data_subset.iloc[-1]
    lowest_val = data_subset.min()
    highest_val = data_subset.max()
    height = highest_val - lowest_val
    val_1_month = data_subset.iloc[-21] if len(data_subset) > 21 else data_subset.iloc[-1]
    bar_x_positions = np.arange(len(available))

    fig = go.Figure()

    # Range bars
    fig.add_trace(go.Bar(
        x=bar_x_positions, y=height, base=lowest_val,
        marker_color="skyblue", width=0.3, name="Range (Low->High)", opacity=0.7
    ))

    # Percentile lines
    percentile_info = [
        {"label": "10th Percentile", "color": "black", "level": 0.1},
        {"label": "25th Percentile", "color": "red", "level": 0.25},
        {"label": "50th Percentile (Median)", "color": "green", "level": 0.5},
        {"label": "75th Percentile", "color": "blue", "level": 0.75},
        {"label": "90th Percentile", "color": "purple", "level": 0.9},
    ]

    for i, ticker in enumerate(available):
        x_left, x_right = i - 0.2, i + 0.2
        for pinfo in percentile_info:
            q_value = quantiles.loc[pinfo["level"], ticker]
            show_legend_flag = (i == 0)
            fig.add_trace(go.Scatter(
                x=[x_left, x_right], y=[q_value, q_value], mode="lines",
                line=dict(color=pinfo["color"], width=2),
                name=pinfo["label"] if show_legend_flag else None,
                hovertemplate=f"<b>{_short_ticker(ticker)}</b><br>{pinfo['label']}: {q_value:.2f}<extra></extra>",
                showlegend=show_legend_flag,
            ))

    # Latest values
    fig.add_trace(go.Scatter(
        x=bar_x_positions, y=recent_val, mode='markers+text',
        text=[f"{val:.2f}" for val in recent_val], textposition="top center",
        marker=dict(color='black', size=12), name="Latest",
        hovertemplate="<b>%{x}</b><br>Latest: %{y:.2f}<extra></extra>"
    ))

    # 1-month ago values
    fig.add_trace(go.Scatter(
        x=bar_x_positions, y=val_1_month, mode='markers',
        marker=dict(color='red', size=14, symbol='star'), name="1-Month Ago",
        hovertemplate="<b>%{x}</b><br>1M Ago: %{y:.2f}<extra></extra>"
    ))

    # Arrows from 1-month ago to latest
    for i, ticker in enumerate(available):
        fig.add_annotation(
            x=bar_x_positions[i], y=recent_val.iloc[i],
            ax=bar_x_positions[i], ay=val_1_month.iloc[i],
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=3, arrowsize=1, arrowwidth=1, arrowcolor="grey", opacity=0.5,
        )

    fig.update_layout(
        title=title,
        xaxis_title="Ticker", yaxis_title="Multiple",
        legend=dict(yanchor="top", y=0.98, xanchor="left", x=0.01),
        height=550, template="plotly_white"
    )
    labels = [_short_ticker(t) for t in available]
    fig.update_xaxes(tickmode='array', tickvals=bar_x_positions, ticktext=labels)
    fig.update_xaxes(showgrid=True)
    fig.update_yaxes(showgrid=True)
    return fig


def plot_time_progression_arrows(
    x_data: pd.DataFrame,
    y_data: pd.DataFrame,
    ticker_list: List[str],
    x_label: str = "EPS Revision (%)",
    y_label: str = "Sales Revision (%)",
    title: str = "EPS vs Sales Revision Time Progression"
) -> go.Figure:
    """
    Plot scatter with arrows showing time progression (3M -> 1M -> 2W -> Now)
    x_data, y_data: DataFrames with tickers as columns, revision values
    """
    fig = go.Figure()

    # Add period legend markers
    for p, c in PERIOD_COLORS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color=c), name=p, legendgroup="periods"
        ))

    # Color palette for tickers
    palette = px.colors.qualitative.Plotly + px.colors.qualitative.Dark24
    ticker_colors = {t: c for t, c in zip(ticker_list, itertools.cycle(palette))}

    periods_rev = list(PERIODS.keys())[::-1]  # 3M -> 2W -> 1M -> Now

    for ticker in ticker_list:
        if ticker not in x_data.columns or ticker not in y_data.columns:
            continue

        xs = []
        ys = []
        for lbl in periods_rev:
            lag = PERIODS[lbl]
            idx = -1 - lag if lag else -1
            if len(x_data) > abs(idx) and len(y_data) > abs(idx):
                x_val = x_data[ticker].iloc[idx]
                y_val = y_data[ticker].iloc[idx]
                xs.append(x_val if pd.notna(x_val) else np.nan)
                ys.append(y_val if pd.notna(y_val) else np.nan)
            else:
                xs.append(np.nan)
                ys.append(np.nan)

        xs = np.array(xs, dtype=float)
        ys = np.array(ys, dtype=float)

        if np.isnan(xs).all() or np.isnan(ys).all():
            continue

        ticker_c = ticker_colors[ticker]
        clean_name = _short_ticker(ticker)

        # Plot line with markers
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers+text",
            text=[""] * (len(xs) - 1) + [clean_name], textposition="top center",
            textfont=dict(size=12, color=ticker_c),
            line=dict(color=ticker_c, width=2),
            marker=dict(size=10, color=[PERIOD_COLORS[p] for p in periods_rev],
                       line=dict(color=ticker_c, width=1)),
            name=clean_name, legendgroup="tickers", showlegend=False
        ))

        # Add arrows (3M -> 2W -> 1M -> Now)
        for i in range(len(xs) - 1):
            if np.isnan(xs[i]) or np.isnan(xs[i+1]) or np.isnan(ys[i]) or np.isnan(ys[i+1]):
                continue
            fig.add_annotation(
                x=xs[i + 1], y=ys[i + 1],
                ax=xs[i], ay=ys[i],
                xref='x', yref='y',
                axref='x', ayref='y',
                showarrow=True,
                arrowhead=3,
                arrowsize=1.5,
                arrowwidth=2.5,
                arrowcolor=ticker_c,
                opacity=0.8
            )

    fig.update_layout(
        title=title,
        xaxis=dict(title=x_label, tickformat=".0f"),
        yaxis=dict(title=y_label, tickformat=".0f"),
        template="plotly_white", height=600,
        legend=dict(orientation="h", y=1.02, x=0)
    )

    # Add reference lines
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.5)

    return fig


# ------------------------------------------------------------------------------------
# Page: Portfolio Overview (Return Analysis)
# ------------------------------------------------------------------------------------
def page_portfolio_overview(portfolio: pd.DataFrame, sp500_data: Dict[str, pd.DataFrame]) -> None:
    st.header("Portfolio Overview")

    if portfolio.empty:
        st.warning("No portfolio data available")
        return

    # Get portfolio with current prices
    pf = get_portfolio_with_prices(portfolio, sp500_data)
    latest_date = get_latest_business_date(sp500_data)

    st.caption(f"Latest Price Date: {latest_date.strftime('%Y-%m-%d')}")

    # Summary Metrics
    st.subheader("Portfolio Summary")

    total_entry = pf['Entry_Value'].sum()
    total_current = pf['Current_Value'].sum()
    total_pnl = pf['PnL'].sum()
    total_return = total_pnl / total_entry if total_entry > 0 else 0

    # Calculate transaction cost adjusted returns
    total_transaction_cost = total_entry * TRANSACTION_COST_RATE
    total_pnl_net = total_pnl - total_transaction_cost
    total_return_net = total_pnl_net / total_entry if total_entry > 0 else 0

    # Add net columns to pf
    pf['Transaction_Cost'] = pf['Entry_Value'] * TRANSACTION_COST_RATE
    pf['PnL_Net'] = pf['PnL'] - pf['Transaction_Cost']
    pf['Return_Net'] = pf['PnL_Net'] / pf['Entry_Value']

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Investment", f"${total_entry:,.2f}")
    c2.metric("Current Value", f"${total_current:,.2f}")
    c3.metric("Transaction Cost Rate", f"{TRANSACTION_COST_RATE*100:.2f}%")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### Gross Return (before cost)")
        c1, c2 = st.columns(2)
        c1.metric("P&L (Gross)", f"${total_pnl:,.2f}")
        c2.metric("Return (Gross)", f"{total_return*100:.2f}%",
                  delta=f"{total_return*100:.2f}%")

    with col2:
        st.markdown("##### Net Return (after cost)")
        c1, c2 = st.columns(2)
        c1.metric("P&L (Net)", f"${total_pnl_net:,.2f}")
        c2.metric("Return (Net)", f"{total_return_net*100:.2f}%",
                  delta=f"{total_return_net*100:.2f}%")

    st.caption(f"Transaction Cost: ${total_transaction_cost:,.2f} ({TRANSACTION_COST_RATE*100:.2f}% of investment)")

    # Individual Holdings Table
    st.subheader("Holdings Detail")

    display_pf = pf.copy()
    display_pf['Short_Ticker'] = display_pf['Ticker'].apply(_short_ticker)
    display_pf['Return_Gross_Pct'] = display_pf['Return'] * 100
    display_pf['Return_Net_Pct'] = display_pf['Return_Net'] * 100
    display_pf['Weight'] = display_pf['Current_Value'] / total_current * 100

    display_cols = ['Short_Ticker', 'Number', 'Entry_Price', 'Current_Price',
                   'Entry_Value', 'Current_Value', 'PnL', 'Return_Gross_Pct',
                   'Transaction_Cost', 'PnL_Net', 'Return_Net_Pct', 'Weight']

    st.dataframe(
        display_pf[display_cols].rename(columns={
            'Short_Ticker': 'Ticker',
            'Number': 'Shares',
            'Entry_Price': 'Entry Price',
            'Current_Price': 'Current Price',
            'Entry_Value': 'Entry Value',
            'Current_Value': 'Current Value',
            'Return_Gross_Pct': 'Return Gross (%)',
            'Transaction_Cost': 'Cost',
            'PnL_Net': 'P&L Net',
            'Return_Net_Pct': 'Return Net (%)',
            'Weight': 'Weight (%)'
        }).style.format({
            'Entry Price': '${:.2f}',
            'Current Price': '${:.2f}',
            'Entry Value': '${:,.2f}',
            'Current Value': '${:,.2f}',
            'PnL': '${:,.2f}',
            'Return Gross (%)': '{:.2f}%',
            'Cost': '${:.2f}',
            'P&L Net': '${:,.2f}',
            'Return Net (%)': '{:.2f}%',
            'Weight (%)': '{:.2f}%'
        }).background_gradient(subset=['Return Net (%)'], cmap='RdYlGn', vmin=-20, vmax=20),
        use_container_width=True
    )

    # Return Bar Chart (Gross vs Net comparison)
    st.subheader("Return by Ticker (Gross vs Net)")

    bar_data = display_pf.sort_values('Return_Net', ascending=True)

    fig_return = go.Figure()

    # Gross Return bars
    fig_return.add_trace(go.Bar(
        x=bar_data['Return_Gross_Pct'],
        y=bar_data['Short_Ticker'],
        orientation='h',
        name='Gross Return',
        marker_color=COLOR_BLUE,
        text=[f"{r:.2f}%" for r in bar_data['Return_Gross_Pct']],
        textposition='outside',
        opacity=0.6
    ))

    # Net Return bars
    colors_net = [COLOR_POSITIVE if r >= 0 else COLOR_NEGATIVE for r in bar_data['Return_Net']]
    fig_return.add_trace(go.Bar(
        x=bar_data['Return_Net_Pct'],
        y=bar_data['Short_Ticker'],
        orientation='h',
        name='Net Return',
        marker_color=colors_net,
        text=[f"{r:.2f}%" for r in bar_data['Return_Net_Pct']],
        textposition='outside'
    ))

    fig_return.update_layout(
        title="Return by Ticker (%) - Gross vs Net",
        xaxis_title="Return (%)",
        yaxis_title="",
        template="plotly_white",
        height=max(300, len(bar_data) * 60),
        barmode='overlay',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig_return.add_vline(x=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_return, use_container_width=True)

    # Portfolio Weight Pie Chart
    st.subheader("Portfolio Allocation")

    fig_pie = px.pie(
        display_pf,
        values='Current_Value',
        names='Short_Ticker',
        title="Portfolio Weight by Ticker"
    )
    fig_pie.update_layout(template="plotly_white")
    st.plotly_chart(fig_pie, use_container_width=True)

    # Price Performance since Entry
    st.subheader("Price Performance Since Entry")

    if 'PX_LAST' in sp500_data:
        prices = sp500_data['PX_LAST']
        entry_date = pf['Date'].min()

        tickers = pf['Ticker'].tolist()
        available_tickers = [t for t in tickers if t in prices.columns]

        if available_tickers:
            price_data = prices.loc[prices.index >= entry_date, available_tickers]

            # Normalize to 100
            normalized = (price_data / price_data.iloc[0]) * 100
            normalized.columns = [_short_ticker(t) for t in normalized.columns]

            fig_perf = go.Figure()
            for col in normalized.columns:
                fig_perf.add_trace(go.Scatter(
                    x=normalized.index,
                    y=normalized[col],
                    mode='lines',
                    name=col
                ))
            fig_perf.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.5)
            fig_perf.update_layout(
                title=f"Price Performance Since Entry ({entry_date.strftime('%Y-%m-%d')})",
                xaxis_title="",
                yaxis_title="Indexed (100 = Entry)",
                template="plotly_white",
                height=500,
                hovermode="x unified"
            )
            st.plotly_chart(fig_perf, use_container_width=True)


# ------------------------------------------------------------------------------------
# Page: Fundamental Analysis
# ------------------------------------------------------------------------------------
def plot_fundamental_time_progression(
    x_data: pd.DataFrame,
    y_data: pd.DataFrame,
    ticker_list: List[str],
    x_label: str = "EPS Change (%)",
    y_label: str = "Sales Change (%)",
    title: str = "EPS vs Sales Time Progression"
) -> go.Figure:
    """
    Plot scatter with arrows showing time progression for fundamental changes
    x_data, y_data: DataFrames with tickers as columns, growth values (already in %)
    """
    fig = go.Figure()

    # Add period legend markers
    for p, c in PERIOD_COLORS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color=c), name=p, legendgroup="periods"
        ))

    # Color palette for tickers
    palette = px.colors.qualitative.Plotly + px.colors.qualitative.Dark24
    ticker_colors = {t: c for t, c in zip(ticker_list, itertools.cycle(palette))}

    periods_rev = list(PERIODS.keys())[::-1]  # 3M -> 2W -> 1M -> Now

    for ticker in ticker_list:
        if ticker not in x_data.columns or ticker not in y_data.columns:
            continue

        xs = []
        ys = []
        for lbl in periods_rev:
            lag = PERIODS[lbl]
            idx = -1 - lag if lag else -1
            if len(x_data) > abs(idx) and len(y_data) > abs(idx):
                x_val = x_data[ticker].iloc[idx]
                y_val = y_data[ticker].iloc[idx]
                xs.append(x_val if pd.notna(x_val) else np.nan)
                ys.append(y_val if pd.notna(y_val) else np.nan)
            else:
                xs.append(np.nan)
                ys.append(np.nan)

        xs = np.array(xs, dtype=float)
        ys = np.array(ys, dtype=float)

        if np.isnan(xs).all() or np.isnan(ys).all():
            continue

        ticker_c = ticker_colors[ticker]
        clean_name = _short_ticker(ticker)

        # Plot line with markers
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers+text",
            text=[""] * (len(xs) - 1) + [clean_name], textposition="top center",
            textfont=dict(size=11, color=ticker_c),
            line=dict(color=ticker_c, width=2),
            marker=dict(size=10, color=[PERIOD_COLORS[p] for p in periods_rev],
                       line=dict(color=ticker_c, width=1)),
            name=clean_name, legendgroup="tickers", showlegend=False
        ))

        # Add arrows (3M -> 2W -> 1M -> Now)
        for i in range(len(xs) - 1):
            if np.isnan(xs[i]) or np.isnan(xs[i+1]) or np.isnan(ys[i]) or np.isnan(ys[i+1]):
                continue
            fig.add_annotation(
                x=xs[i + 1], y=ys[i + 1],
                ax=xs[i], ay=ys[i],
                xref='x', yref='y',
                axref='x', ayref='y',
                showarrow=True,
                arrowhead=3,
                arrowsize=1.5,
                arrowwidth=2.5,
                arrowcolor=ticker_c,
                opacity=0.8
            )

    fig.update_layout(
        title=title,
        xaxis=dict(title=x_label, tickformat=".1f"),
        yaxis=dict(title=y_label, tickformat=".1f"),
        template="plotly_white", height=600,
        legend=dict(orientation="h", y=1.02, x=0)
    )

    # Add reference lines
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.5)

    return fig


def page_fundamentals(portfolio: pd.DataFrame, sp500_data: Dict[str, pd.DataFrame]) -> None:
    st.header("Fundamental Analysis")

    if portfolio.empty:
        st.warning("No portfolio data available")
        return

    tickers = portfolio['Ticker'].tolist()
    short_tickers = [_short_ticker(t) for t in tickers]

    # Create tabs
    tab_progression, tab_level, tab_growth, tab_valuation = st.tabs([
        "Time Progression", "Level", "Growth", "Valuation Bands"
    ])

    # Available metrics
    available_metrics = [k for k in METRIC_LABELS.keys() if k in sp500_data]

    if not available_metrics:
        st.warning("No fundamental data available in S&P500.xlsx")
        return

    with tab_progression:
        st.subheader("Fundamental Time Progression")
        st.caption("Arrow direction: 3M ago -> 2W ago -> 1M ago -> Now")

        # Check required metrics
        required_metrics = ['BEST_EPS', 'BEST_SALES', 'BEST_CALCULATED_FCF']
        available_for_progression = [m for m in required_metrics if m in sp500_data]

        if len(available_for_progression) < 2:
            st.warning("EPS, Sales, FCF data required.")
        else:
            # Calculate 3M growth for each metric
            horizon = 63  # 3 months

            growth_data = {}
            for metric_key in available_for_progression:
                data = sp500_data[metric_key]
                available_tickers = [t for t in tickers if t in data.columns]
                if available_tickers:
                    subset = data[available_tickers]
                    growth = subset.pct_change(horizon) * 100  # Convert to percentage
                    growth_data[metric_key] = growth

            if growth_data:
                # Chart type selection
                chart_type = st.radio(
                    "Chart Type",
                    ["EPS vs Sales", "EPS vs FCF"],
                    horizontal=True
                )

                if chart_type == "EPS vs Sales":
                    if 'BEST_EPS' in growth_data and 'BEST_SALES' in growth_data:
                        eps_growth = growth_data['BEST_EPS']
                        sales_growth = growth_data['BEST_SALES']

                        # Get common tickers
                        common_tickers = list(set(eps_growth.columns) & set(sales_growth.columns))

                        if common_tickers:
                            fig = plot_fundamental_time_progression(
                                eps_growth[common_tickers],
                                sales_growth[common_tickers],
                                common_tickers,
                                x_label="Forward EPS 3M Change (%)",
                                y_label="Forward Sales 3M Change (%)",
                                title="EPS vs Sales Time Progression (3M Change)"
                            )
                            st.plotly_chart(fig, use_container_width=True)

                            st.markdown("""
                            **Quadrant Interpretation:**
                            - **Q1 (Top-Right)**: EPS↑, Sales↑ → Most positive (growth acceleration)
                            - **Q2 (Top-Left)**: EPS↓, Sales↑ → Margin pressure
                            - **Q3 (Bottom-Left)**: EPS↓, Sales↓ → Negative (growth slowdown)
                            - **Q4 (Bottom-Right)**: EPS↑, Sales↓ → Cost efficiency
                            """)
                    else:
                        st.warning("EPS or Sales data not available.")

                elif chart_type == "EPS vs FCF":
                    if 'BEST_EPS' in growth_data and 'BEST_CALCULATED_FCF' in growth_data:
                        eps_growth = growth_data['BEST_EPS']
                        fcf_growth = growth_data['BEST_CALCULATED_FCF']

                        # Get common tickers
                        common_tickers = list(set(eps_growth.columns) & set(fcf_growth.columns))

                        if common_tickers:
                            fig = plot_fundamental_time_progression(
                                eps_growth[common_tickers],
                                fcf_growth[common_tickers],
                                common_tickers,
                                x_label="Forward EPS 3M Change (%)",
                                y_label="Forward FCF 3M Change (%)",
                                title="EPS vs FCF Time Progression (3M Change)"
                            )
                            st.plotly_chart(fig, use_container_width=True)

                            st.markdown("""
                            **Quadrant Interpretation:**
                            - **Q1 (Top-Right)**: EPS↑, FCF↑ → Earnings & cash flow improving together
                            - **Q2 (Top-Left)**: EPS↓, FCF↑ → Cash secured, temporary earnings dip
                            - **Q3 (Bottom-Left)**: EPS↓, FCF↓ → Fundamental deterioration
                            - **Q4 (Bottom-Right)**: EPS↑, FCF↓ → Earnings quality concern (non-cash earnings)
                            """)
                    else:
                        st.warning("EPS or FCF data not available.")

                # Show latest growth values table
                st.subheader("Latest 3M Growth Rates")

                growth_table_data = {}
                for metric_key in available_for_progression:
                    if metric_key in growth_data:
                        latest_growth = growth_data[metric_key].iloc[-1]
                        growth_table_data[METRIC_LABELS.get(metric_key, metric_key)] = latest_growth

                if growth_table_data:
                    growth_df = pd.DataFrame(growth_table_data)
                    growth_df.index = [_short_ticker(t) for t in growth_df.index]
                    growth_df = growth_df.dropna(how='all')

                    st.dataframe(
                        growth_df.style.format("{:.2f}%").background_gradient(
                            cmap='RdYlGn', vmin=-20, vmax=20
                        ),
                        use_container_width=True
                    )

    with tab_level:
        st.subheader("Current Fundamental Levels")

        metric = st.selectbox(
            "Select Metric",
            available_metrics,
            format_func=lambda k: METRIC_LABELS.get(k, k),
            key="level_metric"
        )

        if metric in sp500_data:
            data = sp500_data[metric]
            available_tickers = [t for t in tickers if t in data.columns]

            if available_tickers:
                latest = data[available_tickers].iloc[-1].dropna()
                latest.index = [_short_ticker(t) for t in latest.index]

                # Bar chart
                fig = px.bar(
                    x=latest.index,
                    y=latest.values,
                    title=f"{METRIC_LABELS.get(metric, metric)} - Latest Values",
                    labels={'x': 'Ticker', 'y': METRIC_LABELS.get(metric, metric)}
                )
                fig.update_layout(template="plotly_white", height=400)
                st.plotly_chart(fig, use_container_width=True)

                # Time series
                st.subheader("Historical Trend")

                ts_data = data[available_tickers].copy()
                ts_data.columns = [_short_ticker(t) for t in ts_data.columns]

                # Last 1 year
                one_year_ago = ts_data.index.max() - pd.DateOffset(years=1)
                ts_data = ts_data[ts_data.index >= one_year_ago]

                fig_ts = px.line(ts_data, x=ts_data.index, y=ts_data.columns)
                fig_ts.update_layout(
                    title=f"{METRIC_LABELS.get(metric, metric)} - 1Y Trend",
                    template="plotly_white",
                    height=400,
                    hovermode="x unified"
                )
                st.plotly_chart(fig_ts, use_container_width=True)
            else:
                st.warning(f"No data available for portfolio tickers")

    with tab_growth:
        st.subheader("Fundamental Growth Rates")

        metric_g = st.selectbox(
            "Select Metric",
            available_metrics,
            format_func=lambda k: METRIC_LABELS.get(k, k),
            key="growth_metric"
        )

        horizon_map = {"1M (21d)": 21, "3M (63d)": 63, "1Y (252d)": 252}
        horizon_label = st.selectbox("Horizon", list(horizon_map.keys()), index=1)
        horizon = horizon_map[horizon_label]

        if metric_g in sp500_data:
            data = sp500_data[metric_g]
            available_tickers = [t for t in tickers if t in data.columns]

            if available_tickers:
                # Calculate growth
                subset = data[available_tickers]
                growth = subset.pct_change(horizon).iloc[-1] * 100
                growth.index = [_short_ticker(t) for t in growth.index]
                growth = growth.dropna().sort_values(ascending=False)

                if not growth.empty:
                    colors = [COLOR_POSITIVE if v >= 0 else COLOR_NEGATIVE for v in growth]

                    fig = px.bar(
                        x=growth.index,
                        y=growth.values,
                        title=f"{METRIC_LABELS.get(metric_g, metric_g)} Change ({horizon_label})",
                        labels={'x': 'Ticker', 'y': 'Change (%)'},
                        color=growth.values,
                        color_continuous_scale='RdYlGn'
                    )
                    fig.add_hline(y=0, line_dash="dash", line_color="gray")
                    fig.update_layout(template="plotly_white", height=400, showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)

                    # Table
                    st.dataframe(
                        growth.rename("Change (%)").to_frame().style.format("{:.2f}%"),
                        use_container_width=True
                    )

    with tab_valuation:
        st.subheader("Valuation Bands")

        valuation_metrics = ['BEST_PE_RATIO', 'BEST_PEG_RATIO', 'BEST_EV_TO_BEST_EBITDA']
        available_val_metrics = [m for m in valuation_metrics if m in sp500_data]

        if not available_val_metrics:
            st.warning("No valuation metrics available")
            return

        val_metric = st.selectbox(
            "Select Valuation Metric",
            available_val_metrics,
            format_func=lambda k: METRIC_LABELS.get(k, k),
            key="val_metric"
        )

        if val_metric in sp500_data:
            data = sp500_data[val_metric]

            # Use last 3 years of data for quantiles
            three_years_ago = data.index.max() - pd.DateOffset(years=3)
            data_3y = data[data.index >= three_years_ago]

            fig = plot_valuation_bands(
                data_3y,
                tickers,
                title=f"{METRIC_LABELS.get(val_metric, val_metric)} Valuation Band (3Y)"
            )
            st.plotly_chart(fig, use_container_width=True)


# ------------------------------------------------------------------------------------
# Page: Revision Time Progression
# ------------------------------------------------------------------------------------
def page_revision_progression(portfolio: pd.DataFrame, factset_data: Dict[str, pd.DataFrame]) -> None:
    st.header("Earning/Sales Revision Time Progression")

    if portfolio.empty:
        st.warning("No portfolio data available")
        return

    if not factset_data:
        st.warning("Factset revision data not available")
        st.info(f"Please ensure file exists: {FACTSET_FILE}")
        return

    tickers = portfolio['Ticker'].tolist()

    # Map portfolio tickers to Factset tickers
    # Factset uses format like "MSFT-US^", portfolio uses "MSFT US Equity"
    def to_factset_ticker(ticker: str) -> str:
        parts = ticker.split()
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}^"
        return ticker

    factset_tickers = [to_factset_ticker(t) for t in tickers]

    # Get revision data
    eps_rev = factset_data.get('Fwd SP50 Revision Rate')
    sales_rev = factset_data.get('Sales_Revision')

    if eps_rev is None or sales_rev is None:
        st.warning("EPS or Sales revision data not available")
        return

    # Find matching tickers
    available_eps = [t for t in factset_tickers if t in eps_rev.columns]
    available_sales = [t for t in factset_tickers if t in sales_rev.columns]
    available_both = list(set(available_eps) & set(available_sales))

    if not available_both:
        st.warning("No matching tickers found in revision data")
        st.info("Available tickers in revision data:")
        sample_tickers = list(eps_rev.columns[:20])
        st.write(sample_tickers)
        return

    st.caption(f"Found {len(available_both)} tickers with revision data")

    # Time Progression Chart
    st.subheader("EPS vs Sales Revision Time Progression")
    st.caption("Arrow direction shows revision trend: 3M ago -> 2W ago -> 1M ago -> Now")

    fig = plot_time_progression_arrows(
        eps_rev[available_both],
        sales_rev[available_both],
        available_both,
        x_label="EPS Revision Rate",
        y_label="Sales Revision Rate",
        title="EPS vs Sales Revision Time Progression"
    )
    st.plotly_chart(fig, use_container_width=True)

    # Current Revision Table
    st.subheader("Current Revision Rates")

    latest_eps = eps_rev[available_both].iloc[-1]
    latest_sales = sales_rev[available_both].iloc[-1]

    rev_table = pd.DataFrame({
        'Ticker': [_short_ticker(t.replace('-', ' ').replace('^', '')) for t in available_both],
        'EPS Revision': latest_eps.values,
        'Sales Revision': latest_sales.values
    })

    st.dataframe(
        rev_table.style.format({
            'EPS Revision': '{:.0f}',
            'Sales Revision': '{:.0f}'
        }).background_gradient(subset=['EPS Revision', 'Sales Revision'], cmap='RdYlGn', vmin=-50, vmax=50),
        use_container_width=True
    )

    # EPS Revision Bar Chart
    st.subheader("EPS Revision Rate (Latest)")

    eps_sorted = latest_eps.sort_values(ascending=True)
    eps_labels = [_short_ticker(t.replace('-', ' ').replace('^', '')) for t in eps_sorted.index]
    colors = [COLOR_POSITIVE if v >= 0 else COLOR_NEGATIVE for v in eps_sorted.values]

    fig_eps = go.Figure()
    fig_eps.add_trace(go.Bar(
        x=eps_sorted.values,
        y=eps_labels,
        orientation='h',
        marker_color=colors,
        text=[f"{v:.0f}" for v in eps_sorted.values],
        textposition='outside'
    ))
    fig_eps.update_layout(
        title="EPS Revision Rate",
        xaxis_title="Revision Rate",
        yaxis_title="",
        template="plotly_white",
        height=max(300, len(eps_sorted) * 50)
    )
    fig_eps.add_vline(x=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_eps, use_container_width=True)


# ------------------------------------------------------------------------------------
# Page: RL Portfolio Results
# ------------------------------------------------------------------------------------
def page_rl_portfolio() -> None:
    st.header("RL Portfolio Results")

    # Load data
    daily_perf = load_rl_daily_performance()
    monthly_weights = load_rl_monthly_weights()
    features = load_rl_features()

    if daily_perf.empty:
        st.warning("RL Portfolio result files not found. Please run re_cc.py first.")
        st.info(f"Expected path: {RL_DAILY_PERF_FILE}")
        return

    # Create tabs
    tab_returns, tab_perf, tab_weights, tab_features = st.tabs([
        "Fund Returns", "Performance Graph", "Monthly Weights", "Feature Data"
    ])

    with tab_returns:
        st.subheader("Period Returns (1M / 3M / 6M / 12M)")

        period_returns = calc_rl_period_returns(daily_perf)

        if period_returns:
            # Create metrics display
            st.markdown("##### Portfolio Returns")
            cols = st.columns(4)
            for i, period in enumerate(['1M', '3M', '6M', '12M']):
                port_ret = period_returns['portfolio'].get(period, np.nan)
                bm_ret = period_returns['benchmark'].get(period, np.nan)
                excess = period_returns['excess'].get(period, np.nan)

                with cols[i]:
                    st.metric(
                        label=f"{period} Return",
                        value=f"{port_ret*100:.2f}%" if not np.isnan(port_ret) else "N/A",
                        delta=f"{excess*100:.2f}% vs BM" if not np.isnan(excess) else None
                    )

            st.divider()

            # Create comparison table
            st.markdown("##### Return Comparison Table")
            periods = ['1M', '3M', '6M', '12M']
            table_data = {
                'Period': periods,
                'Portfolio': [f"{period_returns['portfolio'].get(p, np.nan)*100:.2f}%" for p in periods],
                'Benchmark': [f"{period_returns['benchmark'].get(p, np.nan)*100:.2f}%" for p in periods],
                'Excess': [f"{period_returns['excess'].get(p, np.nan)*100:.2f}%" for p in periods]
            }
            st.dataframe(pd.DataFrame(table_data), use_container_width=True)

            # Summary statistics
            st.divider()
            st.markdown("##### Portfolio Statistics")

            # Calculate overall stats
            total_return = daily_perf['portfolio_cumulative'].iloc[-1] - 1
            bm_total_return = daily_perf['benchmark_cumulative'].iloc[-1] - 1
            excess_total = total_return - bm_total_return

            ann_return = _calc_cagr(daily_perf['portfolio_return'])
            ann_bm_return = _calc_cagr(daily_perf['benchmark_return'])
            sharpe = _calc_sharpe(daily_perf['portfolio_return'])
            maxdd = _calc_maxdd(daily_perf['portfolio_return'])

            # Tracking Error
            excess_returns = daily_perf['portfolio_return'] - daily_perf['benchmark_return']
            tracking_error = excess_returns.std() * np.sqrt(252)
            information_ratio = (ann_return - ann_bm_return) / tracking_error if tracking_error > 0 else np.nan

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Return", f"{total_return*100:.2f}%")
            c2.metric("Annual Return", f"{ann_return*100:.2f}%")
            c3.metric("Sharpe Ratio", f"{sharpe:.3f}")
            c4.metric("Max Drawdown", f"{maxdd*100:.2f}%")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("BM Total Return", f"{bm_total_return*100:.2f}%")
            c2.metric("Excess Return", f"{excess_total*100:.2f}%")
            c3.metric("Tracking Error", f"{tracking_error*100:.2f}%")
            c4.metric("Information Ratio", f"{information_ratio:.3f}")

    with tab_perf:
        st.subheader("Performance Graph")

        # Date selector
        min_date = daily_perf.index.min().date()
        max_date = daily_perf.index.max().date()

        col1, col2 = st.columns([1, 3])
        with col1:
            start_date = st.date_input(
                "Start Date",
                value=min_date,
                min_value=min_date,
                max_value=max_date,
                key="rl_start_date"
            )

        # Filter data by start date
        filtered_perf = daily_perf[daily_perf.index >= pd.Timestamp(start_date)]

        if not filtered_perf.empty:
            # Recalculate cumulative returns from start date
            port_cum = (1 + filtered_perf['portfolio_return']).cumprod()
            bm_cum = (1 + filtered_perf['benchmark_return']).cumprod()

            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x=filtered_perf.index,
                y=(port_cum - 1) * 100,
                mode='lines',
                name='Portfolio',
                line=dict(color=COLOR_BLUE, width=2)
            ))

            fig.add_trace(go.Scatter(
                x=filtered_perf.index,
                y=(bm_cum - 1) * 100,
                mode='lines',
                name='Benchmark',
                line=dict(color=COLOR_ORANGE, width=2)
            ))

            fig.update_layout(
                title=f"Cumulative Return (from {start_date})",
                xaxis_title="",
                yaxis_title="Cumulative Return (%)",
                template="plotly_white",
                height=500,
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

            st.plotly_chart(fig, use_container_width=True)

            # Excess return chart
            st.markdown("##### Excess Return (Portfolio - Benchmark)")
            excess_cum = port_cum - bm_cum

            fig_excess = go.Figure()
            fig_excess.add_trace(go.Scatter(
                x=filtered_perf.index,
                y=excess_cum * 100,
                mode='lines',
                name='Excess Return',
                fill='tozeroy',
                fillcolor='rgba(31, 119, 180, 0.3)',
                line=dict(color=COLOR_BLUE, width=2)
            ))
            fig_excess.update_layout(
                title="Cumulative Excess Return",
                xaxis_title="",
                yaxis_title="Excess Return (%)",
                template="plotly_white",
                height=350
            )
            fig_excess.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            st.plotly_chart(fig_excess, use_container_width=True)

    with tab_weights:
        st.subheader("Monthly Stock Weights")

        if monthly_weights.empty:
            st.warning("Monthly weights data not available")
        else:
            # Extract unique tickers from column names
            port_cols = [c for c in monthly_weights.columns if c.endswith('_port')]
            tickers = [c.replace('_port', '') for c in port_cols]

            # Select month to view
            available_months = monthly_weights.index.strftime('%Y-%m').tolist()
            selected_month = st.selectbox("Select Month", available_months, index=len(available_months)-1)

            # Get weights for selected month
            selected_data = monthly_weights[monthly_weights.index.strftime('%Y-%m') == selected_month]

            if not selected_data.empty:
                row = selected_data.iloc[0]

                # Create weight comparison table
                weight_data = []
                for ticker in tickers:
                    port_wt = row.get(f'{ticker}_port', 0)
                    bm_wt = row.get(f'{ticker}_bm', 0)
                    active = row.get(f'{ticker}_active', 0)
                    weight_data.append({
                        'Ticker': ticker,
                        'Portfolio (%)': port_wt * 100,
                        'Benchmark (%)': bm_wt * 100,
                        'Active (%)': active * 100
                    })

                weight_df = pd.DataFrame(weight_data)
                weight_df = weight_df.sort_values('Portfolio (%)', ascending=False)

                # Display table
                st.dataframe(
                    weight_df.style.format({
                        'Portfolio (%)': '{:.2f}%',
                        'Benchmark (%)': '{:.2f}%',
                        'Active (%)': '{:.2f}%'
                    }).background_gradient(subset=['Active (%)'], cmap='RdYlGn', vmin=-10, vmax=10),
                    use_container_width=True
                )

                # Bar chart for portfolio weights
                st.markdown("##### Weight Comparison Chart")
                fig_weights = go.Figure()

                fig_weights.add_trace(go.Bar(
                    x=weight_df['Ticker'],
                    y=weight_df['Portfolio (%)'],
                    name='Portfolio',
                    marker_color=COLOR_BLUE,
                    opacity=0.8
                ))

                fig_weights.add_trace(go.Bar(
                    x=weight_df['Ticker'],
                    y=weight_df['Benchmark (%)'],
                    name='Benchmark',
                    marker_color=COLOR_ORANGE,
                    opacity=0.6
                ))

                fig_weights.update_layout(
                    title=f"Portfolio vs Benchmark Weights ({selected_month})",
                    xaxis_title="",
                    yaxis_title="Weight (%)",
                    template="plotly_white",
                    height=400,
                    barmode='group',
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_weights, use_container_width=True)

                # Active weights bar chart
                st.markdown("##### Active Weights (Overweight/Underweight)")
                active_sorted = weight_df.sort_values('Active (%)', ascending=True)
                colors = [COLOR_POSITIVE if v >= 0 else COLOR_NEGATIVE for v in active_sorted['Active (%)']]

                fig_active = go.Figure()
                fig_active.add_trace(go.Bar(
                    x=active_sorted['Active (%)'],
                    y=active_sorted['Ticker'],
                    orientation='h',
                    marker_color=colors,
                    text=[f"{v:.2f}%" for v in active_sorted['Active (%)']],
                    textposition='outside'
                ))
                fig_active.update_layout(
                    title=f"Active Weights ({selected_month})",
                    xaxis_title="Active Weight (%)",
                    yaxis_title="",
                    template="plotly_white",
                    height=max(300, len(tickers) * 45)
                )
                fig_active.add_vline(x=0, line_dash="dash", line_color="gray")
                st.plotly_chart(fig_active, use_container_width=True)

            # Weight time series
            st.divider()
            st.markdown("##### Weight Time Series")

            selected_ticker = st.selectbox("Select Ticker", tickers, key="weight_ticker")

            if selected_ticker:
                port_col = f'{selected_ticker}_port'
                bm_col = f'{selected_ticker}_bm'

                if port_col in monthly_weights.columns:
                    fig_ts = go.Figure()

                    fig_ts.add_trace(go.Scatter(
                        x=monthly_weights.index,
                        y=monthly_weights[port_col] * 100,
                        mode='lines+markers',
                        name='Portfolio',
                        line=dict(color=COLOR_BLUE, width=2)
                    ))

                    if bm_col in monthly_weights.columns:
                        fig_ts.add_trace(go.Scatter(
                            x=monthly_weights.index,
                            y=monthly_weights[bm_col] * 100,
                            mode='lines+markers',
                            name='Benchmark',
                            line=dict(color=COLOR_ORANGE, width=2)
                        ))

                    fig_ts.update_layout(
                        title=f"{selected_ticker} Weight History",
                        xaxis_title="",
                        yaxis_title="Weight (%)",
                        template="plotly_white",
                        height=400,
                        hovermode="x unified"
                    )
                    st.plotly_chart(fig_ts, use_container_width=True)

    with tab_features:
        st.subheader("Feature Data")

        if not features:
            st.warning("Feature data not available")
            st.info(f"Expected path: {RL_FEATURES_DIR}")
        else:
            available_features = list(features.keys())

            col1, col2 = st.columns([1, 2])
            with col1:
                selected_feature = st.selectbox(
                    "Select Feature",
                    available_features,
                    key="feature_select"
                )

            feature_df = features.get(selected_feature)

            if feature_df is not None and not feature_df.empty:
                tickers = feature_df.columns.tolist()

                # Latest values
                st.markdown(f"##### Latest {selected_feature} Values")
                latest = feature_df.iloc[-1].sort_values(ascending=False)

                fig_latest = px.bar(
                    x=latest.index,
                    y=latest.values,
                    title=f"{selected_feature} - Latest Values ({feature_df.index[-1].strftime('%Y-%m-%d')})",
                    labels={'x': 'Ticker', 'y': selected_feature}
                )
                fig_latest.update_layout(template="plotly_white", height=350)
                st.plotly_chart(fig_latest, use_container_width=True)

                # Time series
                st.markdown(f"##### {selected_feature} Time Series")

                # Period selector
                period_options = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252, "All": None}
                selected_period = st.selectbox("Period", list(period_options.keys()), index=2, key="feature_period")

                days = period_options[selected_period]
                if days:
                    plot_df = feature_df.iloc[-days:] if len(feature_df) >= days else feature_df
                else:
                    plot_df = feature_df

                # Ticker multi-select
                selected_tickers = st.multiselect(
                    "Select Tickers",
                    tickers,
                    default=tickers[:5],
                    key="feature_tickers"
                )

                if selected_tickers:
                    fig_ts = px.line(
                        plot_df[selected_tickers],
                        x=plot_df.index,
                        y=selected_tickers,
                        title=f"{selected_feature} Time Series"
                    )
                    fig_ts.update_layout(
                        template="plotly_white",
                        height=450,
                        hovermode="x unified",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig_ts, use_container_width=True)

                # Data table
                st.markdown(f"##### Raw Data (Latest 30 Days)")
                st.dataframe(
                    feature_df.tail(30).style.format("{:.3f}"),
                    use_container_width=True
                )


# ------------------------------------------------------------------------------------
# Main Application
# ------------------------------------------------------------------------------------
def main():
    st.title("Personal Portfolio Dashboard")

    # Load data
    with st.spinner("Loading data..."):
        portfolio = load_portfolio()
        sp500_data = load_sp500_data()
        factset_data = load_factset_revision()

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["Portfolio Overview", "RL Portfolio", "Fundamental Analysis", "Revision Time Progression"]
    )

    # Sidebar portfolio info
    if not portfolio.empty:
        st.sidebar.divider()
        st.sidebar.subheader("Portfolio Holdings")
        for _, row in portfolio.iterrows():
            st.sidebar.write(f"- {_short_ticker(row['Ticker'])}: {row['Number']} shares")

    # Page routing
    if page == "Portfolio Overview":
        page_portfolio_overview(portfolio, sp500_data)
    elif page == "RL Portfolio":
        page_rl_portfolio()
    elif page == "Fundamental Analysis":
        page_fundamentals(portfolio, sp500_data)
    elif page == "Revision Time Progression":
        page_revision_progression(portfolio, factset_data)


if __name__ == "__main__":
    main()
