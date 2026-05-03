---
name: streamlit-universe-analytics
description: Self_Port Universe 시트의 Ticker_Arin 종목들에 대해 S&P500.xlsx의 BEST_EPS / BEST_SALES Forward 추정치를 SPX Index 영업일 마스터에 reindex하고, 3M(63일)/12M(252일) 추정치 모멘텀을 계산해 최근 3년 시계열 그래프와 모멘텀 테이블을 그리는 스킬. Fwd EPS/Sales 시계열, 추정치 모멘텀, 영업일 정렬이 필요한 모든 작업에 사용한다.
---

# Streamlit Universe Analytics

## 왜 이 스킬이 필요한가
컨센서스 추정치는 시장이 미래에 대해 가지고 있는 기대를 반영한다. 추정치가 변동하는 속도(모멘텀)는 종목의 펀더멘털 모멘텀의 가장 빠른 시그널이다. 이 스킬은 그것을 시계열로 시각화한다. 또한 영업일 마스터를 통일하지 않으면 종목 간 비교 불가능하므로 SPX Index 영업일을 단일 기준으로 사용한다.

## 핵심 산식 (사용자 확정)

### 추정치 모멘텀
```python
# panel: SPX Index 영업일에 reindex된 BEST_EPS 또는 BEST_SALES
# columns = Bloomberg 티커, index = 영업일

momentum_3m = panel / panel.shift(63) - 1   # 63 영업일 ≈ 3 개월
momentum_12m = panel / panel.shift(252) - 1  # 252 영업일 ≈ 12 개월
```

`shift(N)`이 NaN을 만드는 첫 N 행은 정상 동작이다.

### 최근 3년 슬라이스
```python
last_n_years = 3
slice_len = 252 * last_n_years  # 약 756 영업일
recent = panel.iloc[-slice_len:]
```

모멘텀 계산은 슬라이스 **이전에** 수행 (252 영업일 더 이전 데이터 필요).

## 영업일 reindex 패턴

```python
def reindex_to_business_days(df: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    df = df.sort_index()
    out = df.reindex(calendar, method=None)  # 마스터 영업일에만 정렬
    out = out.ffill()  # 영업일 사이 빈칸은 직전값
    return out
```

`method="ffill"`을 reindex에 직접 넣지 말고 별도 호출(인덱스 정합성 보장).

## UI 패턴

### 1. 사이드바 다중 선택
```python
universe = load_universe_tickers()
default = universe[:3] if len(universe) >= 3 else universe
selected = st.sidebar.multiselect(
    "분석할 종목 선택",
    options=universe,
    default=default,
)
if not selected:
    st.warning("종목을 1개 이상 선택해 주세요")
    return
```

### 2. Fwd EPS / Sales 시계열 차트
```python
import plotly.graph_objects as go

def render_metric_chart(panel_recent: pd.DataFrame, selected: list[str], title: str):
    fig = go.Figure()
    for ticker in selected:
        if ticker not in panel_recent.columns:
            continue
        s = panel_recent[ticker].dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=ticker, mode="lines"))
    fig.update_layout(title=title, height=400, hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
```

### 3. 모멘텀 테이블
```python
def latest_momentum(panel: pd.DataFrame, periods: int) -> pd.Series:
    """선택 종목의 최신 영업일 모멘텀."""
    mom = panel / panel.shift(periods) - 1
    return mom.iloc[-1]  # 마지막 영업일

eps_3m = latest_momentum(eps_panel, 63).loc[selected]
eps_12m = latest_momentum(eps_panel, 252).loc[selected]
sales_3m = latest_momentum(sales_panel, 63).loc[selected]
sales_12m = latest_momentum(sales_panel, 252).loc[selected]

table = pd.DataFrame({
    "EPS 3M": eps_3m,
    "EPS 12M": eps_12m,
    "Sales 3M": sales_3m,
    "Sales 12M": sales_12m,
}).applymap(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "—")

st.dataframe(table, use_container_width=True)
```

## 데이터 흐름 요약

```
Universe.Ticker_Arin (Bloomberg 형식 그대로)
    │
    ▼
S&P500.xlsx의 BEST_EPS / BEST_SALES 컬럼 인덱싱
    │
    ▼
Index.xlsx의 SPX Index 영업일에 reindex + ffill
    │
    ▼
모멘텀 계산: panel / panel.shift(N) - 1
    │
    ▼
최근 3년 슬라이스 → Plotly 차트 + 모멘텀 테이블
```

## 에러 핸들링

- Ticker_Arin 일부가 BEST_EPS 컬럼에 없음 → 차트·테이블에서 자동 제외, 사이드바 multiselect에서 `(데이터 없음)` 라벨로 표시
- BEST_EPS 시트에서 일부 종목의 값이 모두 NaN → 차트는 빈 라인, 테이블은 `—`
- 데이터가 252영업일 이하 → 12M 모멘텀 NaN, 테이블에 `—` 표시

## 성능 팁
- panel 로딩과 reindex는 모두 `@st.cache_data`로 감싼다 (`port/lib/data_loader.py`에서 처리)
- 사용자가 종목 선택을 바꿀 때마다 panel 자체를 다시 로드하지 않도록 캐시 키 설계
