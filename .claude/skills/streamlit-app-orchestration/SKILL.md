---
name: streamlit-app-orchestration
description: 기존 Self_port.py에 새로운 탭(아린이 포트폴리오 모니터, 유니버스 분석)을 통합하는 스킬. st.tabs 추가, lib 모듈 import, 캐시 무효화, 6세 친화 테마(폰트/색상)가 필요할 때 사용한다. 기존 7개 탭 기능은 절대 건드리지 않는다.
---

# Streamlit App Orchestration

## 왜 이 스킬이 필요한가
`Self_port.py`는 이미 7개의 기존 기능(포트폴리오, RL 성과, ULTRA RL, AICODEX 등)을 담고 있는 큰 파일이다. 새 두 탭을 추가하면서 기존 기능을 깨면 안 된다. 또한 데이터 로딩이 무거우므로 캐싱과 모듈 분리가 필수이다.

## 통합 원칙

1. **기존 코드 수정 최소화.** 새 import 추가, 새 탭 추가만. 기존 함수/탭은 손대지 않는다.
2. **모듈 분리.** 새 탭 로직은 `port/lib/tab_portfolio_monitor.py`, `port/lib/tab_universe_analyst.py`에 둔다. `Self_port.py`는 import해서 호출만 한다.
3. **탭 라벨에 이모지.** 사용자가 시각적으로 즉시 구분할 수 있도록.
4. **사이드바 공유.** 두 새 탭이 사이드바를 사용한다면 `st.session_state`나 탭 내부의 컨테이너 사용 (사이드바 충돌 방지).

## Self_port.py 통합 패턴

### Step 1: import 추가 (파일 상단, 기존 import 그룹 뒤)
```python
from port.lib.tab_portfolio_monitor import render_portfolio_monitor_tab
from port.lib.tab_universe_analyst import render_universe_analyst_tab
```

> 만약 `port/`가 모듈 경로가 아니라면 (Self_port.py가 port/ 안에서 실행됨), 단순히:
> ```python
> from lib.tab_portfolio_monitor import render_portfolio_monitor_tab
> from lib.tab_universe_analyst import render_universe_analyst_tab
> ```

### Step 2: st.tabs 확장
기존 코드에 `tabs = st.tabs([...])` 같은 라인이 있으면, 그 리스트에 두 새 라벨을 **추가**한다 (앞이 아닌 뒤에 추가하면 기존 인덱스 보존):

```python
tab_labels = [...기존 라벨..., "🎀 아린이 포트폴리오", "🔍 유니버스 분석"]
tabs = st.tabs(tab_labels)

# ... 기존 with tabs[0]: ... 등 그대로 유지

with tabs[-2]:
    render_portfolio_monitor_tab()
with tabs[-1]:
    render_universe_analyst_tab()
```

`tabs[-2]`, `tabs[-1]`을 쓰면 기존 인덱스 변경 없이 안전하게 끝에 추가.

### Step 3: 캐시 무효화 버튼 (선택)
사이드바에 "데이터 새로고침" 버튼 추가 — Self_Port.xlsx에 새 행 추가 후 즉시 반영:

```python
if st.sidebar.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()
```

## 6세 친화 테마

### 페이지 설정 (이미 있다면 그대로)
```python
st.set_page_config(
    page_title="가족 투자 모니터",
    page_icon="🎀",
    layout="wide",
)
```

### 색감
- 양수 수익률: 녹색 (`#2ECC71`)
- 음수 수익률: 빨강 (`#E74C3C`)
- 중립: 회색 (`#95A5A6`)

`st.metric`의 `delta`는 자동으로 색을 입혀준다. Plotly에서는:
```python
fig.update_traces(line_color="#2ECC71" if cum_return >= 0 else "#E74C3C")
```

### 폰트 크기
종목 카드는 `st.metric` 기본 크기로 충분히 크다. 본문 텍스트가 작아 보이면:
```python
st.markdown("### 큰 제목")  # h3 사이즈
```

## 절대 하지 말 것

- 기존 import 순서 재배치
- 기존 탭의 with 블록 들여쓰기 변경
- Self_Port.xlsx 경로를 새로 정의 (이미 기존에 있음 — 재사용)
- `st.cache_data` 데코레이터를 Self_port.py 안에 새로 정의 (lib/ 안에서 처리)
- `.claude/commands/`에 슬래시 커맨드 생성

## 검증 (변경 후 즉시)

1. `streamlit run port/Self_port.py` 실행
2. 기존 탭들이 모두 정상 동작하는지 클릭해서 확인
3. 새 두 탭이 끝에 등장하는지
4. 콘솔에 import 에러 없는지
