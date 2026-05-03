---
name: data-quality-qa
description: data-engineer 산출과 두 탭 빌더 산출의 경계면 정합성을 점진적으로 검증하는 QA 스킬. 시트명/컬럼명 일치, 영업일 reindex 정확도, 추정치 모멘텀 산식, 일별/누적 수익률 일관성, UI shape 비교가 필요한 모든 검증 작업에 사용한다.
---

# Data Quality QA

## 왜 이 스킬이 필요한가
"함수가 import되는가?"는 약한 검증이다. 진짜 버그는 경계면에서 일어난다 — 데이터 로더가 반환하는 컬럼명과 탭 빌더가 기대하는 컬럼명이 다를 때, 영업일 reindex가 ffill을 빼먹어 첫 영업일이 NaN으로 시작할 때 등. 이 스킬은 **경계면 교차 비교(cross-check)**의 절차와 체크리스트를 제공한다.

## 핵심 원칙

1. **존재가 아니라 매칭.** A가 반환하는 shape == B가 기대하는 shape인가.
2. **점진적 호출.** 모듈 하나가 완성되는 즉시 검증. 끝나고 한꺼번에 검증하면 어디서 깨졌는지 추적 불가.
3. **실제 실행.** 정적 코드 리뷰가 아니라 Python으로 호출해 결과를 print.
4. **부동소수는 isclose.** 일별 합 vs 누적 수익률 비교 시 `np.isclose(rtol=1e-5)`.
5. **never tag along** — 빌더의 자체 평가에 의존하지 않는다.

## 체크포인트

### CP-1: data-engineer 완료
```python
import pandas as pd
from lib.data_loader import (
    load_self_port_holdings, load_universe_tickers,
    load_sp500_panel, load_spx_index, load_px_last,
)

h = load_self_port_holdings()
assert "Entry_Price" in h.columns, f"got {h.columns.tolist()}"
assert "Date" in h.columns
assert "Ticker" in h.columns
print(f"holdings rows: {len(h)}")  # 기대: 2 (Sheet2)

u = load_universe_tickers()
assert len(u) > 0
assert all("Equity" in t for t in u), f"non-Bloomberg tickers: {u}"
print(f"universe size: {len(u)}")  # 기대: ~9

eps = load_sp500_panel("BEST_EPS")
assert isinstance(eps.index, pd.DatetimeIndex)
print(f"BEST_EPS shape: {eps.shape}")  # 기대: ~4500 x ~65

spx = load_spx_index()
print(f"SPX days: {len(spx)}")  # 기대: ~3099
```

### CP-2: portfolio-monitor-builder 완료
```python
from lib.tab_portfolio_monitor import _emoji, _compute_returns

# 이모티콘 매핑
assert _emoji(0.15) == "📈"
assert _emoji(-0.15) == "📉"
assert _emoji(0.05) == "➡️"
assert _emoji(-0.05) == "➡️"
assert _emoji(0.0) == "➡️"

# 누적 수익률 = 마지막 종가 / 진입가 - 1
holdings = load_self_port_holdings()
px = load_px_last()
returns = _compute_returns(holdings, px)
for t in returns.index:
    expected = px[t].iloc[-1] / holdings.loc[t, "Entry_Price"] - 1
    assert np.isclose(returns.loc[t, "cum_return"], expected, rtol=1e-5)
```

### CP-3: universe-analyst-builder 완료
```python
from lib.tab_universe_analyst import _compute_momentum
from lib.calendar_utils import get_business_calendar, reindex_to_business_days

cal = get_business_calendar()
eps = load_sp500_panel("BEST_EPS")
eps_aligned = reindex_to_business_days(eps, cal)

# 영업일 정렬 후 NaN 비율 합리적
nan_ratio = eps_aligned.isna().mean().mean()
assert nan_ratio < 0.5, f"too many NaN after reindex: {nan_ratio:.2%}"

# 모멘텀 산식
mom_3m = _compute_momentum(eps_aligned, 63)
assert mom_3m.iloc[:63].isna().all().all(), "first 63 rows should be NaN"
assert mom_3m.iloc[63:].notna().any().any()

# 최근 3년 길이
recent = eps_aligned.iloc[-756:]
assert 700 < len(recent) < 800
```

### CP-4: Self_port.py 통합 후
```bash
streamlit run port/Self_port.py --server.headless true --server.port 8511 &
sleep 5
curl -s http://localhost:8511 | grep -q "아린이 포트폴리오"
curl -s http://localhost:8511 | grep -q "유니버스 분석"
kill %1
```

콘솔 로그에 `ImportError`, `KeyError`, `AttributeError`가 없어야 한다.

## 보고서 형식 (`port/_workspace/qa_report_{phaseN}.md`)

```markdown
# QA Report — CP-N (YYYY-MM-DD HH:MM)

## Summary
- Total checks: X
- Passed: Y
- Failed: Z

## Checks

### ✅ holdings.columns contains Entry_Price
- Expected: 'Entry_Price' in columns
- Got: ['Date', 'Ticker', 'Number', 'Entry_Price', 'Price']
- Status: PASS

### ❌ universe size
- Expected: > 0
- Got: 0 (Universe 시트가 비어 있음)
- Status: FAIL
- Action: data-engineer에게 시트 로딩 로직 점검 요청
```

## 자주 놓치는 경계면 버그

| 패턴 | 어떻게 잡나 |
|---|---|
| 컬럼명에 미묘한 공백 (`'Entry_Price '`) | `df.columns.tolist()`을 직접 print하고 strip 적용 여부 확인 |
| reindex 후 첫 행이 NaN | `eps_aligned.head(5)`을 print해서 실제로 ffill 되는지 확인 |
| 티커가 컬럼에 없음 | `set(universe) - set(panel.columns)`를 계산해 누락 리스트 보고 |
| 부동소수 비교 실패 | `np.isclose(..., rtol=1e-5, atol=1e-8)` 사용 |
| 캐시가 stale | `st.cache_data.clear()` 호출 후 재실행 |
| 월별 탭 누락 | 보유 시작일 ~ 오늘의 모든 월이 탭에 있는지 set 비교 |

## 협업
- 실패 항목은 해당 빌더에게 즉시 통보 (SendMessage 또는 메시지 체인)
- 코드 수정은 빌더가 한다. QA는 검증만 한다 (관심의 분리).
