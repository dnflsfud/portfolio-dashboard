---
name: streamlit-portfolio-monitoring
description: Self_Port.xlsx Sheet2 보유 종목 데이터로 누적 수익률 차트, 일별 수익률 월별 서브탭, 상승/보합/하락 이모티콘을 보여주는 Streamlit 컴포넌트를 만든다. 6세 자녀 친화 UI(큰 폰트, 강한 색감, 이모티콘)가 필요한 포트폴리오 모니터링 작업에 사용한다.
---

# Streamlit Portfolio Monitoring

## 왜 이 스킬이 필요한가
사용자가 6살 아린이와 함께 보면서 "오늘 우리 주식이 올랐는지" 즉시 알 수 있어야 한다. 따라서 이모티콘과 색감이 핵심이고, 숫자는 보조다. 또한 Sheet2는 종목별 진입일이 다를 수 있으므로 누적 수익률은 종목별로 별도 baseline에서 시작해야 한다.

## 핵심 산식

### 진입가 vs 현재가 누적 수익률
```python
cumulative_return = (current_price / entry_price - 1) * 100  # %
```

### 일별 수익률 (PX_LAST 시계열에서)
```python
# px: PX_LAST에서 가져온 종목별 일별 종가 시리즈
daily_return = px.pct_change().dropna() * 100  # %
```

### 누적 수익률 시계열 (그래프용)
```python
# 진입일부터 현재까지, 종목별
entry_date = holdings.loc[ticker, "Date"]
px_after_entry = px.loc[entry_date:]
cum_series = (px_after_entry / px_after_entry.iloc[0] - 1) * 100
```

## 이모티콘 매핑 (사용자 확정 임계값)

```python
def emoji_for(daily_return_pct: float) -> str:
    if daily_return_pct >= 0.1:
        return "📈"
    if daily_return_pct <= -0.1:
        return "📉"
    return "➡️"
```

NaN/빈 값 → `"❓"` 처리.

## UI 패턴

### 1. 종목 카드 (상단)
`st.columns(N)`로 가로 배치. 각 종목별:

```python
col.metric(
    label=f"{emoji} {ticker}",
    value=f"${current_price:.2f}",
    delta=f"{cum_return:+.2f}% (진입 ${entry:.2f})",
)
```

### 2. 누적 수익률 차트 (Plotly)
종목별 라인 차트. 진입일 = 0% 기준선:

```python
import plotly.graph_objects as go

fig = go.Figure()
for ticker in holdings.index:
    cum = compute_cum_series(ticker)
    fig.add_trace(go.Scatter(x=cum.index, y=cum.values, name=ticker, mode="lines"))
fig.add_hline(y=0, line_dash="dash", line_color="gray")
fig.update_layout(yaxis_title="누적 수익률 (%)", height=400)
st.plotly_chart(fig, use_container_width=True)
```

### 3. 월별 서브탭 (st.tabs)
보유 기간만큼만 탭 생성:

```python
months = sorted({d.strftime("%Y-%m") for d in trading_days_in_holding_period})
tabs = st.tabs(months)
for tab, ym in zip(tabs, months):
    with tab:
        sub = daily_returns_df.loc[ym]
        sub["📊"] = sub["일별수익률"].apply(emoji_for)
        st.dataframe(sub, use_container_width=True)
```

월별 라벨 형식: `YYYY-MM` (예: `2024-03`).

## 6세 친화 디자인 원칙

1. **큰 폰트**: `st.markdown` 사용 시 `### 종목 이름` 같은 제목 레벨로 키운다.
2. **강한 색감**: 이모티콘만으로 부족하면 `st.success`(녹색), `st.error`(빨강) 같은 컴포넌트로 보강.
3. **숫자 포맷**: 소수점 2자리, % 기호 명확히. `f"{x:+.2f}%"` 패턴.
4. **장식 이모지**: 탭 라벨이나 섹션 헤더에 `🎀`, `⭐` 같은 친화적 이모지 한 두개 추가 (과하지 않게).

## Yahoo Finance 라이브 가격 폴백

PX_LAST는 사용자가 Bloomberg에서 다시 export할 때만 갱신된다. 이 때문에:
- 진입일이 PX_LAST 마지막일보다 미래일 때
- PX_LAST 마지막일이 SPX Index 영업일 마스터의 마지막보다 옛날일 때

→ **lib/live_price.py의 `fetch_yahoo_latest(bloomberg_ticker)`**로 yfinance에서 최신가를 가져온다. 사이드바 토글 `🌐 Yahoo Finance 라이브 가격 사용`로 on/off.

Bloomberg → Yahoo 매핑은 단순한 첫 토큰 추출:
- `'AAPL US Equity'` → `'AAPL'`
- `'BRK/B US Equity'` → `'BRK-B'` (slash → dash, Yahoo 컨벤션)

`_compute_returns(h, px, use_yahoo_fallback=True, business_calendar=cal)` 가 source 컬럼을 반환:
- `'PX_LAST'`: 정상
- `'yahoo'`: Yahoo 폴백 사용됨 (사용자에게 success 배너 표시)
- `'PX_LAST(stale)'`: Yahoo도 실패, PX_LAST 옛 값 사용 (warning 배너)
- `'none'`: 어디서도 가격 없음

캐싱: `@st.cache_data(ttl=300)`로 5분간 재사용 (API 호출 절약).

## 에러 핸들링

- 보유 종목이 PX_LAST와 Yahoo 모두에 없음 → 카드에 "데이터 없음 ❓" 표시
- Sheet2가 비어 있음 → `st.info("아직 보유한 종목이 없어요!")` 친화적 메시지
- yfinance import 실패 (오프라인 등) → `yfinance_available()=False`, PX_LAST만 사용
- 부동소수 0 비교는 `abs(x) < 1e-9` 사용

## 모듈 구조 (참고)

```python
# port/lib/tab_portfolio_monitor.py

def render_portfolio_monitor_tab() -> None:
    holdings = load_self_port_holdings()
    px = load_px_last()
    if holdings.empty:
        st.info("아직 보유한 종목이 없어요!")
        return
    _render_holding_cards(holdings, px)
    _render_cumulative_chart(holdings, px)
    _render_monthly_tabs(holdings, px)
```
